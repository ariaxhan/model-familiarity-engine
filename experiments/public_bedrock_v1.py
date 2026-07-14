#!/usr/bin/env python3
"""Bounded, immutable public Bedrock evidence runner.

This file is intentionally outside the package API. It runs the three bundled public
synthetic debugging tasks, proves the judge with repeated semantic floor probes, and
writes a checksum-verified evidence packet. Dry-run does not construct a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

# Allow direct execution from a source checkout without installing the package. This
# does not modify or couple to the active PyPI release lane.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

JUDGE_MODEL = "qwen.qwen3-235b-a22b-2507-v1:0"
PUBLIC_TASK_IDS = ("ios_zoom", "cover_crop", "annual_price")
FLOOR_PROBE_COUNT = 8
NONBLANK_FLOOR_PROBE_COUNT = 6
DEFAULT_MODELS = (
    "deepseek.v3.2",
    "google.gemma-3-12b-it",
    "us.amazon.nova-lite-v1:0",
    "us.meta.llama4-scout-17b-instruct-v1:0",
    "openai.gpt-oss-20b-1:0",
)
CONDITIONS = ("cold", "appended-nudge")
MAX_BUDGET_USD = 5.0
SUBJECT_MAX_TOKENS = 1024
JUDGE_MAX_TOKENS = 600
FLOOR_REPETITIONS = 5
SUBJECT_INPUT_TOKEN_BOUND = 2048
JUDGE_INPUT_TOKEN_BOUND = 4096
PRICING_AS_OF = "2026-07-14"

# Conservative public preflight bounds in USD per million input/output tokens. These
# are not billing receipts. They are deliberately fixed so a planned run is reproducible.
TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "deepseek.v3.2": (0.62, 1.85),
    "google.gemma-3-12b-it": (0.09, 0.29),
    "us.amazon.nova-lite-v1:0": (0.06, 0.24),
    "us.meta.llama4-scout-17b-instruct-v1:0": (0.17, 0.66),
    "openai.gpt-oss-20b-1:0": (0.09, 0.39),
    JUDGE_MODEL: (0.25, 1.00),
}
VALID_DIVERGENCES = {"equivalent", "better", "worse", "novel"}
MAX_JUDGE_RESPONSE_CHARS = 16_384


class StrictVerdictError(ValueError):
    """The raw judge response failed the public experiment schema."""

    def __init__(
        self, code: str, message: str, safe_evidence: dict[str, Any] | None = None
    ) -> None:
        self.code = code
        self.safe_evidence = safe_evidence or {}
        super().__init__(f"{code}: {message}")


class _CaptureProvider:
    """Transparent provider wrapper retaining only normalized usage, never raw SDK data."""

    def __init__(self, provider: Any):
        self.provider = provider
        self.response: Any = None

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        self.response = await self.provider.complete(*args, **kwargs)
        return self.response


def _normalized_judge_usage(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    return {
        "judge_latency_ms": round(response.latency_ms, 1),
        "judge_input_tokens": response.input_tokens,
        "judge_output_tokens": response.output_tokens,
        "judge_provider_reported_cost_usd": response.cost_usd,
    }


def _extract_single_json_object(text: str) -> dict[str, Any]:
    """Extract exactly one bounded JSON object, tolerating only non-object wrappers."""
    if len(text) > MAX_JUDGE_RESPONSE_CHARS:
        raise StrictVerdictError("response_too_large", "judge response exceeded safe bound")
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            break
        try:
            value, relative_end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        end = start + relative_end
        if isinstance(value, dict):
            candidates.append((start, end, value))
            if len(candidates) > 1:
                raise StrictVerdictError(
                    "multiple_objects", "judge response contained multiple JSON objects"
                )
            cursor = end
        else:
            cursor = start + 1
    if not candidates:
        raise StrictVerdictError("no_object", "judge response contained no JSON object")
    start, end, value = candidates[0]
    wrapper = text[:start] + text[end:]
    if "{" in wrapper or "}" in wrapper:
        raise StrictVerdictError("invalid_wrapper", "wrapper contained unmatched object syntax")
    return value


@dataclass(frozen=True)
class Plan:
    mode: str
    models: tuple[str, ...]
    task_ids: tuple[str, ...]
    conditions: tuple[str, ...]
    k: int
    floor_repetitions: int
    subject_calls: int
    subject_judge_calls: int
    floor_judge_calls: int
    total_calls: int
    max_input_tokens: int
    max_output_tokens: int
    projected_max_cost_usd: float
    budget_usd: float


def _price(model: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = TOKEN_PRICES[model]
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def build_plan(
    mode: str,
    models: Sequence[str],
    k: int,
    budget_usd: float = MAX_BUDGET_USD,
) -> Plan:
    """Validate a run and calculate its explicit worst-case calls/tokens/cost."""
    if mode not in {"dry-run", "floor-only", "smoke", "full"}:
        raise ValueError(f"unknown mode: {mode}")
    cleaned = tuple(model.strip() for model in models)
    if not cleaned or any(not model for model in cleaned) or len(set(cleaned)) != len(cleaned):
        raise ValueError("model roster must be non-empty, unique, non-blank model IDs")
    if any(model not in TOKEN_PRICES or model == JUDGE_MODEL for model in cleaned):
        raise ValueError("model roster contains an unpriced or judge model")
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")
    if mode in {"dry-run", "full"} and k < 5:
        raise ValueError("publishable/full runs require k >= 5")
    if not 0 < budget_usd <= MAX_BUDGET_USD:
        raise ValueError(f"budget must be positive and <= USD {MAX_BUDGET_USD:.2f}")

    all_task_ids = PUBLIC_TASK_IDS
    if mode == "floor-only":
        task_ids: tuple[str, ...] = ()
        conditions: tuple[str, ...] = ()
        active_models: tuple[str, ...] = ()
    elif mode == "smoke":
        task_ids = (all_task_ids[0],)
        conditions = (CONDITIONS[0],)
        active_models = (cleaned[0],)
    else:
        task_ids = all_task_ids
        conditions = CONDITIONS
        active_models = cleaned

    subject_calls = len(active_models) * len(task_ids) * len(conditions) * k
    subject_judge_calls = subject_calls
    # Two of the eight floor probes are blank and deterministically bypass the judge.
    floor_judge_calls = NONBLANK_FLOOR_PROBE_COUNT * FLOOR_REPETITIONS
    judge_calls = subject_judge_calls + floor_judge_calls

    subject_input = subject_calls * SUBJECT_INPUT_TOKEN_BOUND
    subject_output = subject_calls * SUBJECT_MAX_TOKENS
    judge_input = judge_calls * JUDGE_INPUT_TOKEN_BOUND
    judge_output = judge_calls * JUDGE_MAX_TOKENS
    projected = judge_calls * _price(
        JUDGE_MODEL, JUDGE_INPUT_TOKEN_BOUND, JUDGE_MAX_TOKENS
    )
    if subject_calls:
        calls_per_model = len(task_ids) * len(conditions) * k
        projected += sum(
            calls_per_model
            * _price(model, SUBJECT_INPUT_TOKEN_BOUND, SUBJECT_MAX_TOKENS)
            for model in active_models
        )
    projected = round(projected, 6)
    if projected > budget_usd:
        raise ValueError(
            f"projected maximum cost USD {projected:.6f} exceeds budget USD {budget_usd:.2f}"
        )

    return Plan(
        mode=mode,
        models=active_models,
        task_ids=task_ids,
        conditions=conditions,
        k=k,
        floor_repetitions=FLOOR_REPETITIONS,
        subject_calls=subject_calls,
        subject_judge_calls=subject_judge_calls,
        floor_judge_calls=floor_judge_calls,
        total_calls=subject_calls + judge_calls,
        max_input_tokens=subject_input + judge_input,
        max_output_tokens=subject_output + judge_output,
        projected_max_cost_usd=projected,
        budget_usd=budget_usd,
    )


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Return a two-sided Wilson 95% interval, including explicit n=0 behavior."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("Wilson counts require 0 <= successes <= n")
    if n == 0:
        return (0.0, 1.0)
    proportion = successes / n
    denominator = 1 + z * z / n
    centre = (proportion + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / n + z * z / (4 * n * n))
    margin /= denominator
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    if successes == 0:
        low = 0.0
    if successes == n:
        high = 1.0
    return (round(low, 6), round(high, 6))


async def strict_judge(
    task: Any,
    output: str,
    provider: Any,
    judge_model: str = JUDGE_MODEL,
) -> dict[str, Any]:
    """Judge output while validating raw JSON types before accepting the verdict."""
    from model_familiarity.judge import judge

    spine_reached, spine_detail = task.spine(output)
    if not output or not output.strip():
        return {
            "reached": False,
            "divergence": "worse",
            "how": "model produced no answer text (empty output)",
            "spine_reached": spine_reached,
            "spine_detail": spine_detail,
            "agrees_with_spine": spine_reached is False,
            "judge_called": False,
        }

    capture = _CaptureProvider(provider)
    verdict = await judge(
        task,
        output,
        capture,
        judge_model=judge_model,
        max_tokens=JUDGE_MAX_TOKENS,
    )
    usage = _normalized_judge_usage(capture.response)
    try:
        raw = _extract_single_json_object(verdict.raw_text)
    except StrictVerdictError as error:
        error.safe_evidence.update(usage)
        raise
    if not isinstance(raw, dict):
        raise StrictVerdictError("no_object", "judge response is not a JSON object", usage)
    if type(raw.get("reached")) is not bool:  # noqa: E721 - exact bool excludes 0/1
        raise StrictVerdictError(
            "invalid_boolean", "judge reached must be a JSON boolean", usage
        )
    divergence = raw.get("divergence")
    if type(divergence) is not str or divergence not in VALID_DIVERGENCES:
        raise StrictVerdictError("invalid_divergence", "judge divergence is invalid", usage)
    if raw["reached"] is False and divergence != "worse":
        raise StrictVerdictError(
            "contradiction", "judge divergence contradicts reached=false", usage
        )
    if raw["reached"] is True and divergence == "worse":
        raise StrictVerdictError(
            "contradiction", "judge divergence contradicts reached=true", usage
        )
    how = raw.get("how", "")
    if type(how) is not str:  # noqa: E721 - strict JSON schema
        raise StrictVerdictError("invalid_how", "judge how must be a string", usage)
    return {
        "reached": raw["reached"],
        "divergence": divergence,
        "how": how.strip(),
        "spine_reached": verdict.spine_reached,
        "spine_detail": verdict.spine_detail,
        "agrees_with_spine": raw["reached"] == verdict.spine_reached,
        "judge_called": True,
        **usage,
    }


def _timestamp() -> str:
    current = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    return current.replace("+00:00", "Z")


def subject_record(
    *,
    model: str,
    task_id: str,
    condition: str,
    sample_index: int,
    reached: bool,
) -> dict[str, Any]:
    """Small public helper for constructing completed evidence in tests/tools."""
    return {
        "schema": "public-bedrock-v1/evidence",
        "phase": "subject",
        "attempt_id": f"subject/{model}/{task_id}/{condition}/{sample_index}",
        "timestamp": "2026-07-14T00:00:00Z",
        "model": model,
        "task_id": task_id,
        "condition": condition,
        "sample_index": sample_index,
        "status": "complete",
        "answered": True,
        "reached": reached,
        "divergence": "equivalent" if reached else "worse",
        "judge_called": True,
        "agrees_with_spine": True,
    }


def _cell_key(task_id: str, condition: str) -> str:
    return f"{task_id}/{condition}"


def _aggregate_cell(
    subject: Sequence[dict[str, Any]], model: str, task_id: str, condition: str
) -> dict[str, Any]:
    attempts = [
        record
        for record in subject
        if record.get("model") == model
        and record.get("task_id") == task_id
        and record.get("condition") == condition
    ]
    complete = [
        record
        for record in attempts
        if record.get("status") == "complete" and type(record.get("reached")) is bool
    ]
    reached = sum(record["reached"] is True for record in complete)
    low, high = wilson_interval(reached, len(complete))
    subject_latencies = [
        record["latency_ms"]
        for record in complete
        if record.get("latency_ms") is not None
    ]
    subject_input = sum(record.get("input_tokens") or 0 for record in complete)
    subject_output = sum(record.get("output_tokens") or 0 for record in complete)
    judge_input = sum(record.get("judge_input_tokens") or 0 for record in complete)
    judge_output = sum(record.get("judge_output_tokens") or 0 for record in complete)
    estimated_cost = sum(
        _price(record["model"], record.get("input_tokens") or 0, record.get("output_tokens") or 0)
        + _price(
            JUDGE_MODEL,
            record.get("judge_input_tokens") or 0,
            record.get("judge_output_tokens") or 0,
        )
        for record in complete
    )
    return {
        "attempted": len(attempts),
        "completed": len(complete),
        "errors": len(attempts) - len(complete),
        "blank_misses": sum(record.get("answered") is False for record in complete),
        "reached": reached,
        "rate": round(reached / len(complete), 6) if complete else None,
        "wilson_95": [low, high],
        "spine_agreements": sum(record.get("agrees_with_spine") is True for record in complete),
        "usage": {
            "subject_input_tokens": subject_input,
            "subject_output_tokens": subject_output,
            "judge_input_tokens": judge_input,
            "judge_output_tokens": judge_output,
            "subject_latency_ms_median": (
                round(statistics.median(subject_latencies), 1) if subject_latencies else None
            ),
            "estimated_cost_usd": round(estimated_cost, 8),
        },
    }


def _model_usage(cells: dict[str, Any]) -> dict[str, Any]:
    usage = [cell["usage"] for cell in cells.values()]
    latency_values = [
        item["subject_latency_ms_median"]
        for item in usage
        if item["subject_latency_ms_median"] is not None
    ]
    return {
        "subject_input_tokens": sum(item["subject_input_tokens"] for item in usage),
        "subject_output_tokens": sum(item["subject_output_tokens"] for item in usage),
        "judge_input_tokens": sum(item["judge_input_tokens"] for item in usage),
        "judge_output_tokens": sum(item["judge_output_tokens"] for item in usage),
        "median_of_cell_subject_latency_medians_ms": (
            round(statistics.median(latency_values), 1) if latency_values else None
        ),
        "estimated_cost_usd": round(sum(item["estimated_cost_usd"] for item in usage), 8),
    }


def aggregate_records(
    records: Sequence[dict[str, Any]], plan: Plan, floor_passed: bool
) -> dict[str, Any]:
    """Aggregate only immutable evidence and expose publication/tie-out gates."""
    subject = [record for record in records if record.get("phase") == "subject"]
    floor = [record for record in records if record.get("phase") == "floor"]
    model_results: dict[str, Any] = {}
    all_cells_complete = bool(plan.models and plan.task_ids and plan.conditions)

    for model in plan.models:
        cells = {
            _cell_key(task_id, condition): _aggregate_cell(subject, model, task_id, condition)
            for task_id in plan.task_ids
            for condition in plan.conditions
        }
        if any(cell["completed"] != plan.k for cell in cells.values()):
            all_cells_complete = False
        model_results[model] = {"cells": cells, "usage": _model_usage(cells)}

    expected_subject = plan.subject_calls
    completed_subject = sum(
        record.get("status") == "complete" and type(record.get("reached")) is bool
        for record in subject
    )
    floor_completed = sum(record.get("status") == "complete" for record in floor)
    expected_floor = FLOOR_PROBE_COUNT * plan.floor_repetitions
    floor_evidence_complete = len(floor) == expected_floor and all(
        record.get("status") == "complete" and record.get("passed") is True
        for record in floor
    )
    floor_agreements = sum(
        record.get("status") == "complete" and record.get("agrees_with_spine") is True
        for record in floor
    )
    publishable = (
        plan.mode == "full"
        and plan.k >= 5
        and floor_passed
        and floor_evidence_complete
        and all_cells_complete
        and len(subject) == expected_subject
        and completed_subject == expected_subject
    )
    return {
        "schema": "public-bedrock-v1/summary",
        "publishable": publishable,
        "scope": "three public synthetic known-outcome debugging tasks",
        "floor": {
            "semantic_expected_label_passed": floor_passed,
            "attempted": len(floor),
            "expected_attempts": expected_floor,
            "completed": floor_completed,
            "spine_agreements": floor_agreements,
            "spine_agreement_rate": (
                round(floor_agreements / floor_completed, 6) if floor_completed else None
            ),
            "note": (
                "Semantic expected-label accuracy is the gate. The keyword spine is a "
                "separate fallible calibration signal, not ground truth."
            ),
        },
        "tie_out": {
            "record_count": len(records),
            "floor_attempts": len(floor),
            "subject_attempts": len(subject),
            "expected_subject_attempts": expected_subject,
            "completed_subject_attempts": completed_subject,
            "missing_subject_attempts": max(0, expected_subject - completed_subject),
        },
        "models": model_results,
    }


def render_model_card(model: str, plan: Plan, summary: dict[str, Any], run_date: str) -> str:
    """Render a narrow card with no ranking or production-role claim."""
    model_data = summary.get("models", {}).get(model, {"cells": {}})
    rows = []
    for cell, result in sorted(model_data["cells"].items()):
        rate = "n/a" if result["rate"] is None else f"{result['rate'] * 100:.1f}%"
        interval = result["wilson_95"]
        rows.append(
            f"| {cell} | {result['completed']}/{plan.k} | {result['reached']} | {rate} | "
            f"[{interval[0]:.3f}, {interval[1]:.3f}] |"
        )
    table = "\n".join(rows) if rows else "| no completed subject cells | 0 | 0 | n/a | [0, 1] |"
    status = "publishable" if summary.get("publishable") else "not publishable"
    usage = model_data.get("usage", {})
    protocol = summary.get("protocol", {})
    protocol_hash = protocol.get("protocol_sha256", "unavailable")
    task_hashes = ", ".join(
        f"`{task_id}` `{digest}`"
        for task_id, digest in sorted(protocol.get("task_sha256", {}).items())
    )
    return f"""# Model card: `{model}`

Status: **{status}**. Snapshot date: {run_date}.

## Scope and method

Corpus: three public synthetic debugging tasks; this run planned {len(plan.task_ids)} task(s),
{len(plan.conditions)} condition(s), and k={plan.k} repeated invocation(s) per cell. Verdicts use
`{JUDGE_MODEL}` after a repeated semantic expected-label floor. The keyword spine is reported as
a fallible calibration signal and is not treated as ground truth.

Protocol SHA-256: `{protocol_hash}`.

Task SHA-256 values: {task_hashes or "unavailable"}.

| Task / condition | Completed | Reached | Rate | Wilson 95% interval |
|---|---:|---:|---:|---:|
{table}

Recorded subject usage: {usage.get('subject_input_tokens', 0)} input tokens and
{usage.get('subject_output_tokens', 0)} output tokens. Median of cell-level subject latency
medians: {usage.get('median_of_cell_subject_latency_medians_ms')} ms. Conservative estimated
subject-plus-judge cost from recorded token counts: USD {usage.get('estimated_cost_usd', 0):.8f}.

## Limitations

This is not a broad model ranking, a production-routing recommendation, or evidence about a
general software-engineering role. It is a dated snapshot of three small synthetic known-outcome
debugging tasks on Bedrock. Rates have substantial uncertainty at this sample size; provider,
model, and judge behavior can change. No comparison should be generalized beyond these tasks,
conditions, model IDs, and the stated judge.

The appended-nudge condition is a fresh single call containing the original prompt plus a
content-free frustrated follow-up. It does not include the model's cold answer, so any difference
measures prompt sensitivity, not recovery or self-correction. Repetitions use temperature 0 and
measure observed invocation stability. Wilson intervals are descriptive; they do not establish
independent, identically distributed population uncertainty.
"""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def _task_hash(task: Any) -> str:
    public_task = {
        "task_id": task.task_id,
        "prompt": task.prompt,
        "known_outcome": task.known_outcome,
        "followup": task.followup,
    }
    return hashlib.sha256(_canonical_json(public_task).encode()).hexdigest()


def _protocol_metadata(plan: Plan) -> dict[str, Any]:
    """Hash every semantic/config input needed to identify this exact protocol."""
    from model_familiarity.floor import PROBES
    from model_familiarity.tasks import load_tasks

    tasks = load_tasks()
    task_payloads = [
        {
            "task_id": task.task_id,
            "prompt": task.prompt,
            "known_outcome": task.known_outcome,
            "followup": task.followup,
        }
        for task in tasks
    ]
    runner_sha256 = sha256_file(Path(__file__))
    payload = {
        "runner_sha256": runner_sha256,
        "tasks": task_payloads,
        "floor_probes": PROBES,
        "models": plan.models,
        "conditions": plan.conditions,
        "k": plan.k,
        "judge_model": JUDGE_MODEL,
        "prices": {model: TOKEN_PRICES[model] for model in (*plan.models, JUDGE_MODEL)},
        "pricing_as_of": PRICING_AS_OF,
        "subject_max_tokens": SUBJECT_MAX_TOKENS,
        "judge_max_tokens": JUDGE_MAX_TOKENS,
        "subject_input_token_bound": SUBJECT_INPUT_TOKEN_BOUND,
        "judge_input_token_bound": JUDGE_INPUT_TOKEN_BOUND,
    }
    return {
        "protocol_sha256": hashlib.sha256(_canonical_json(payload).encode()).hexdigest(),
        "runner_sha256": runner_sha256,
        "task_sha256": {task.task_id: _task_hash(task) for task in tasks},
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_model_name(model: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in model)


def _write_cards(directory: Path, plan: Plan, summary: dict[str, Any], run_date: str) -> None:
    from model_familiarity.redact import assert_obj_clean

    directory.mkdir()
    for model in plan.models:
        card = render_model_card(model, plan, summary, run_date)
        assert_obj_clean(card)
        (directory / f"{_safe_model_name(model)}.md").write_text(card, encoding="utf-8")


def _file_entries(directory: Path) -> list[dict[str, Any]]:
    paths = sorted(
        [path for path in directory.rglob("*") if path.is_file()],
        key=lambda path: path.relative_to(directory).as_posix(),
    )
    return [
        {
            "path": path.relative_to(directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def _remove_temporary_packet(directory: Path) -> None:
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    directory.rmdir()


def write_immutable_packet(
    output_root: Path,
    run_id: str,
    plan: Plan,
    records: Sequence[dict[str, Any]],
    floor_passed: bool,
    created_at: str,
    code_revision: str,
) -> Path:
    """Atomically create and verify a run directory; never overwrite a run ID."""
    safe_run_id_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not run_id or any(char not in safe_run_id_chars for char in run_id):
        raise ValueError("run ID may contain only letters, digits, '-' and '_'")
    output_root = Path(output_root)
    final = output_root / run_id
    temporary = output_root / f".{run_id}.tmp"
    if final.exists() or temporary.exists():
        raise FileExistsError(f"immutable run already exists: {run_id}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        from model_familiarity.redact import assert_obj_clean

        for record in records:
            assert_obj_clean(record)
        evidence_text = "".join(_canonical_json(record) for record in records)
        (temporary / "evidence.jsonl").write_text(evidence_text, encoding="utf-8")
        persisted_records = [json.loads(line) for line in evidence_text.splitlines() if line]
        summary = aggregate_records(persisted_records, plan, floor_passed)
        summary["protocol"] = _protocol_metadata(plan)
        (temporary / "summary.json").write_text(_canonical_json(summary), encoding="utf-8")
        _write_cards(temporary / "model-cards", plan, summary, created_at[:10])

        file_entries = _file_entries(temporary)
        checksums_text = "".join(
            f"{entry['sha256']}  {entry['path']}\n" for entry in file_entries
        )
        (temporary / "checksums.sha256").write_text(checksums_text, encoding="utf-8")
        manifest = {
            "schema": "public-bedrock-v1/manifest",
            "run_id": run_id,
            "created_at": created_at,
            "code_revision": code_revision,
            "pricing_as_of": PRICING_AS_OF,
            "judge_model": JUDGE_MODEL,
            "protocol": summary["protocol"],
            "plan": asdict(plan),
            "tie_out": summary["tie_out"],
            "publishable": summary["publishable"],
            "files": file_entries,
            "checksums_file": "checksums.sha256",
        }
        assert_obj_clean(manifest)
        (temporary / "manifest.json").write_text(_canonical_json(manifest), encoding="utf-8")

        # Verify every checksum and the evidence/manifest tie-out before atomic rename.
        for entry in file_entries:
            if sha256_file(temporary / entry["path"]) != entry["sha256"]:
                raise RuntimeError(f"checksum verification failed: {entry['path']}")
        evidence_count = sum(1 for line in evidence_text.splitlines() if line.strip())
        if evidence_count != manifest["tie_out"]["record_count"]:
            raise RuntimeError("manifest/evidence record count mismatch")
        temporary.rename(final)
    except BaseException:
        _remove_temporary_packet(temporary)
        raise
    return final


def export_publishable(packet: Path, public_root: Path) -> Path:
    """Atomically export aggregate-only public artifacts from a publishable packet."""
    from model_familiarity.redact import assert_obj_clean

    packet = Path(packet)
    summary = json.loads((packet / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    if not summary.get("publishable") or not manifest.get("publishable"):
        raise ValueError("only a publishable full packet may be exported")
    run_id = manifest["run_id"]
    public_root = Path(public_root)
    final = public_root / run_id
    temporary = public_root / f".{run_id}.tmp"
    if final.exists() or temporary.exists():
        raise FileExistsError(f"immutable public export already exists: {run_id}")
    public_root.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        (temporary / "summary.json").write_bytes((packet / "summary.json").read_bytes())
        public_cards = temporary / "model-cards"
        public_cards.mkdir()
        for source in sorted((packet / "model-cards").glob("*.md")):
            (public_cards / source.name).write_bytes(source.read_bytes())
        files = _file_entries(temporary)
        receipt = {
            "schema": "public-bedrock-v1/publication",
            "run_id": run_id,
            "created_at": manifest["created_at"],
            "protocol": summary["protocol"],
            "source_manifest_sha256": sha256_file(packet / "manifest.json"),
            "aggregate_files": files,
            "contains_raw_evidence": False,
        }
        assert_obj_clean(receipt)
        (temporary / "publication.json").write_text(_canonical_json(receipt), encoding="utf-8")
        temporary.rename(final)
    except BaseException:
        _remove_temporary_packet(temporary)
        raise
    return final


def _public_error_record(base: dict[str, Any], error_kind: str) -> dict[str, Any]:
    return {
        **base,
        "status": "error",
        "error_kind": error_kind,
        "error": "call failed; provider details intentionally omitted from public evidence",
    }


async def _run_floor(provider: Any, repetitions: int) -> tuple[list[dict[str, Any]], bool]:
    from model_familiarity.floor import PROBES
    from model_familiarity.redact import assert_obj_clean
    from model_familiarity.tasks import get_task

    if len(PROBES) != FLOOR_PROBE_COUNT:
        raise RuntimeError("floor probe set changed; create a new dated experiment version")
    records: list[dict[str, Any]] = []
    total = len(PROBES) * repetitions
    for sample_index in range(1, repetitions + 1):
        for probe_index, (task_id, kind, answer) in enumerate(PROBES, start=1):
            task = get_task(task_id)
            base = {
                "schema": "public-bedrock-v1/evidence",
                "phase": "floor",
                "attempt_id": f"floor/{task_id}/{kind}/{probe_index}/{sample_index}",
                "timestamp": _timestamp(),
                "judge_model": JUDGE_MODEL,
                "task_id": task_id,
                "task_sha256": _task_hash(task),
                "probe_kind": kind,
                "probe_index": probe_index,
                "sample_index": sample_index,
            }
            try:
                verdict = await strict_judge(task, answer, provider, JUDGE_MODEL)
                expected_reached = kind == "correct_diff"
                record = {
                    **base,
                    "status": "complete",
                    "expected_reached": expected_reached,
                    "passed": verdict["reached"] is expected_reached,
                    **verdict,
                }
            except StrictVerdictError as error:
                record = _public_error_record(
                    {**base, **error.safe_evidence}, f"strict_verdict_error/{error.code}"
                )
            except Exception:  # noqa: BLE001 - public packet deliberately omits SDK details
                record = _public_error_record(base, "provider_error")
            assert_obj_clean(record)
            records.append(record)
            if len(records) % len(PROBES) == 0 or len(records) == total:
                print(f"floor progress: {len(records)}/{total}")
    expected = FLOOR_PROBE_COUNT * repetitions
    passed = len(records) == expected and all(
        record.get("status") == "complete" and record.get("passed") is True
        for record in records
    )
    return records, passed


async def _run_subjects(provider: Any, plan: Plan) -> list[dict[str, Any]]:
    from model_familiarity.redact import assert_obj_clean
    from model_familiarity.replay import replay_task
    from model_familiarity.tasks import load_tasks

    records: list[dict[str, Any]] = []
    tasks = {task.task_id: task for task in load_tasks()}
    completed_attempts = 0
    for model in plan.models:
        for task_id in plan.task_ids:
            task = tasks[task_id]
            for condition in plan.conditions:
                for sample_index in range(1, plan.k + 1):
                    base = {
                        "schema": "public-bedrock-v1/evidence",
                        "phase": "subject",
                        "attempt_id": f"subject/{model}/{task_id}/{condition}/{sample_index}",
                        "timestamp": _timestamp(),
                        "model": model,
                        "task_id": task_id,
                        "task_sha256": _task_hash(task),
                        "condition": condition,
                        "sample_index": sample_index,
                    }
                    subject_evidence: dict[str, Any] = {}
                    try:
                        replay = await replay_task(
                            task,
                            provider,
                            model,
                            "guided" if condition == "appended-nudge" else condition,
                            max_tokens=SUBJECT_MAX_TOKENS,
                        )
                        # Fail closed before the answer is sent to the judge or persisted.
                        assert_obj_clean(replay.output)
                        subject_evidence = {
                            "answered": bool(replay.output.strip()),
                            "output": replay.output,
                            "latency_ms": round(replay.latency_ms, 1),
                            "input_tokens": replay.input_tokens,
                            "output_tokens": replay.output_tokens,
                            "provider_reported_cost_usd": replay.cost_usd,
                            "judge_model": JUDGE_MODEL,
                        }
                        verdict = await strict_judge(task, replay.output, provider, JUDGE_MODEL)
                        record = {
                            **base,
                            "status": "complete",
                            **subject_evidence,
                            **verdict,
                        }
                    except StrictVerdictError as error:
                        record = _public_error_record(
                            {**base, **subject_evidence, **error.safe_evidence},
                            f"strict_verdict_error/{error.code}",
                        )
                    except Exception:  # noqa: BLE001 - no raw SDK/identity/path leakage
                        record = _public_error_record(base, "provider_or_redaction_error")
                    assert_obj_clean(record)
                    records.append(record)
                    completed_attempts += 1
                    if completed_attempts % 10 == 0 or completed_attempts == plan.subject_calls:
                        print(f"subject progress: {completed_attempts}/{plan.subject_calls}")
    return records


def _code_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run_live(
    plan: Plan,
    output_root: Path,
    run_id: str,
    provider_factory: Callable[..., Any],
    profile: str | None,
    region: str | None,
) -> Path:
    provider = provider_factory("bedrock", profile=profile, region=region)
    floor_records, floor_passed = await _run_floor(provider, plan.floor_repetitions)
    records = list(floor_records)
    if floor_passed and plan.mode != "floor-only":
        records.extend(await _run_subjects(provider, plan))
    created_at = _timestamp()
    return write_immutable_packet(
        output_root,
        run_id,
        plan,
        records,
        floor_passed,
        created_at,
        _code_revision(),
    )


def _print_plan(plan: Plan) -> None:
    print(f"mode: {plan.mode}")
    print(f"models: {len(plan.models)}")
    print(f"k: {plan.k}")
    print(f"floor repetitions: {plan.floor_repetitions}")
    print(f"planned calls: {plan.total_calls}")
    print(f"  subject calls: {plan.subject_calls}")
    print(f"  judge calls: {plan.subject_judge_calls + plan.floor_judge_calls}")
    print(f"maximum input tokens: {plan.max_input_tokens}")
    print(f"maximum output tokens: {plan.max_output_tokens}")
    print(f"projected maximum cost: USD {plan.projected_max_cost_usd:.6f}")
    print(f"hard cost ceiling: USD {MAX_BUDGET_USD:.2f}")
    print(f"pricing bounds dated: {PRICING_AS_OF}")


def _default_provider_factory(name: str, **kwargs: Any) -> Any:
    if name != "bedrock":
        raise ValueError("public Bedrock v1 only supports the bedrock provider")
    from model_familiarity.providers.bedrock import BedrockProvider

    return BedrockProvider(profile=kwargs.get("profile"), region=kwargs.get("region"))


def _add_common_arguments(parser: argparse.ArgumentParser, default_k: int) -> None:
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--k", type=int, default=default_k)
    parser.add_argument("--budget-usd", type=float, default=MAX_BUDGET_USD)
    parser.add_argument(
        "--output-root", type=Path, default=REPO_ROOT / "results" / "public-bedrock-v1"
    )
    parser.add_argument(
        "--public-root",
        type=Path,
        default=REPO_ROOT / "docs" / "model-cards" / "public-bedrock-v1",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--profile", help="AWS profile used in memory only; never persisted")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _add_common_arguments(commands.add_parser("dry-run"), 5)
    _add_common_arguments(commands.add_parser("floor-only"), 5)
    _add_common_arguments(commands.add_parser("smoke"), 1)
    _add_common_arguments(commands.add_parser("full"), 5)
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    provider_factory: Callable[..., Any] = _default_provider_factory,
) -> int:
    args = _parser().parse_args(argv)
    plan = build_plan(args.command, args.models, args.k, args.budget_usd)
    _print_plan(plan)
    if args.command == "dry-run":
        print("dry-run: PASS (zero provider calls; no artifacts created)")
        return 0
    run_id = args.run_id or (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    packet = asyncio.run(
        run_live(
            plan,
            args.output_root,
            run_id,
            provider_factory,
            args.profile,
            args.region,
        )
    )
    summary = json.loads((packet / "summary.json").read_text())
    print(f"evidence packet: {packet}")
    floor_label = "PASS" if summary["floor"]["semantic_expected_label_passed"] else "FAIL"
    print(f"semantic floor: {floor_label}")
    print(f"publishable: {summary['publishable']}")
    if summary["publishable"]:
        public_export = export_publishable(packet, args.public_root)
        print(f"public aggregate export: {public_export}")
    return 0 if summary["floor"]["semantic_expected_label_passed"] else 2


def main() -> None:
    try:
        raise SystemExit(run_cli())
    except (ValueError, FileExistsError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
