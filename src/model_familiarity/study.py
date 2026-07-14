"""Frozen-study config layer, the executable seam between the lab and this instrument.

An evaluation protocol is designed before data collection, then expressed as a YAML config
under ``configs/studies/<study_id>.yaml``. This module is that protocol's validator and dry-run
planner. It never calls a model API: ``validate`` checks a config against the instrument's
structural invariants, ``plan`` prints the full execution plan (cell grid, call counts,
certification precondition, hash check) entirely offline.

Schema (YAML):

  study_id: str                      experiment: exp0|exp1|exp2      status: draft|frozen
  protocol:
    lab_docs: [paths]                # pointers to public design docs
    protocol_hash: str|null          # REQUIRED + must match the live hash when frozen
    rubric_version: str              # must match instrument_health.RUBRIC_VERSION
  certification:
    require: CERTIFIED|CONDITIONALLY CERTIFIED|null   # non-null for behavioral studies
    gates_file: path                 # Instrument Health verdict (relative to repo root)
  environment: {model: str}
  judges: [{key, model, family, provider}]   # >=3 seats spanning >=3 families (doctrine D6)
  subjects: [model ids]
  design: {k: int, challenges: all|[ids], max_turns: int}
  blinding: {judges_blind_to_subject: bool}  # must be true for behavioral studies
  exclusions: [{id, rule, action}]           # pre-registered BEFORE data; non-empty for exp1+
  analysis: {...}                            # informational, the lab doc is the design of record

Validation enforces, offline, the same invariants the runtime enforces loudly:
env != every judge != every subject (``assert_distinct``), a 3-family judge panel,
challenges drawn from the frozen registry, k >= 5 for behavioral headline cells (prereg
Tension 2), pre-registered exclusions, and hash/rubric pinning for frozen configs.

Run:  python -m model_familiarity.study <validate|plan> <config.yaml>
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from model_familiarity.blinding import CANDIDATE_FAMILIES
from model_familiarity.challenges import EXECUTION_ANCHORED, load_challenges
from model_familiarity.instrument_health import RUBRIC_VERSION, protocol_hash
from model_familiarity.panel import DEFAULT_PANEL, EXP0_ENV_MODEL, JudgeSpec, assert_distinct

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPERIMENTS = ("exp0", "exp1", "exp2")
BEHAVIORAL = ("exp1", "exp2")  # studies that make model claims, gated on certification
STATUSES = ("draft", "frozen")
EXCLUSION_ACTIONS = ("drop", "rerun", "abort", "report", "forbidden")
# Instrument Health verdicts, ranked. A study's certification.require names the minimum.
VERDICT_RANK = {"NOT CERTIFIED": 0, "CONDITIONALLY CERTIFIED": 1, "CERTIFIED": 2}
DEFAULT_GATES_FILE = "findings/exp0/gates.json"
DEFAULT_MAX_TURNS = 6
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVIEWED_SOURCE_MANIFEST_SHA256 = (
    "1d35deaa95c833f59a4a14ad4d92515ca2b5bc22c44d5d6253c58cdc5e5bc08a"
)
_REVIEWED_SOURCE_SHARDS = {
    "floor.json": "5f8551bd2878d7d7008c9adaa5b2e6515e2d4db5a8b287a927d490056f848174",
    "verdicts.json": "c0b3993d288ed46a1666776e629f054b59b580fd88a4cae37feeb3f67b511a26",
    "rescore.json": "b4506e3b187a6a2579fe471a296449d8cca28e384334a81eccf429c1818e6a17",
    "blind.json": "5bb68ec3ab07f6f71c90ae1db5ea592ed86ff657a11bebfe2479ebee7e5d5595",
    "oracle-anchor.json": "419d08cdc9d150454646b950f175f72df0e563238a2a5c20fbcc54b8ed4d94a2",
}


def load_config(path: str | Path) -> dict:
    """Read a study YAML. Raises FileNotFoundError / yaml.YAMLError on a broken file."""
    cfg = yaml.safe_load(Path(path).read_text())
    if not isinstance(cfg, dict):
        raise ValueError(f"study config {path} is not a mapping")
    return cfg


def _judge_specs(cfg: dict) -> list[JudgeSpec]:
    return [
        JudgeSpec(j.get("key", ""), j.get("model", ""), j.get("family", ""),
                  j.get("provider", ""))
        for j in cfg.get("judges", []) if isinstance(j, dict)
    ]


def _configured_panel(cfg: dict) -> list[dict[str, str]]:
    return [
        {"key": judge.key, "model": judge.model, "family": judge.family,
         "provider_key": judge.provider_key}
        for judge in _judge_specs(cfg)
    ]


def _certified_panel() -> list[dict[str, str]]:
    return [
        {"key": judge.key, "model": judge.model, "family": judge.family,
         "provider_key": judge.provider_key}
        for judge in DEFAULT_PANEL
    ]


def resolve_challenges(cfg: dict) -> list[str]:
    """Expand design.challenges ('all' or an explicit id list) against the frozen registry."""
    spec = (cfg.get("design") or {}).get("challenges", "all")
    registry = [c.challenge_id for c in load_challenges()]
    if spec == "all":
        return registry
    return list(spec) if isinstance(spec, list) else []


def validate_config(cfg: dict) -> tuple[list[str], list[str]]:
    """Validate one study config. Returns (errors, warnings); empty errors == valid.

    Pure and offline: reads the frozen challenge registry and the live protocol hash from
    code, touches no file other than what the caller already loaded, calls no model API.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(cfg, dict):
        return ["study config must be a mapping"], warnings

    for key in ("study_id", "experiment", "status", "environment", "judges", "subjects",
                "design"):
        if not cfg.get(key):
            errors.append(f"missing required field: {key}")
    for key in ("study_id", "experiment", "status"):
        if key in cfg and not isinstance(cfg[key], str):
            errors.append(f"{key} must be a string")
    for key in ("environment", "design", "protocol", "certification", "blinding"):
        if key in cfg and cfg[key] is not None and not isinstance(cfg[key], dict):
            errors.append(f"{key} must be a mapping")
    for key in ("judges", "subjects", "exclusions"):
        if key in cfg and cfg[key] is not None and not isinstance(cfg[key], list):
            errors.append(f"{key} must be a list")
    if isinstance(cfg.get("judges"), list) and any(
        not isinstance(judge, dict) for judge in cfg["judges"]
    ):
        errors.append("every judges entry must be a mapping")
    elif isinstance(cfg.get("judges"), list):
        for index, judge in enumerate(cfg["judges"]):
            for field in ("key", "model", "family", "provider"):
                if field in judge and not isinstance(judge[field], str):
                    errors.append(f"judges[{index}].{field} must be a string")
    if isinstance(cfg.get("subjects"), list) and any(
        not isinstance(subject, str) for subject in cfg["subjects"]
    ):
        errors.append("every subjects entry must be a string")
    if isinstance(cfg.get("exclusions"), list) and any(
        not isinstance(exclusion, dict) for exclusion in cfg["exclusions"]
    ):
        errors.append("every exclusions entry must be a mapping")
    environment = cfg.get("environment")
    if isinstance(environment, dict) and "model" in environment \
            and not isinstance(environment["model"], str):
        errors.append("environment.model must be a string")
    design = cfg.get("design")
    if isinstance(design, dict):
        challenges = design.get("challenges", "all")
        if challenges != "all" and (
            not isinstance(challenges, list)
            or any(not isinstance(challenge, str) for challenge in challenges)
        ):
            errors.append("design.challenges must be 'all' or a list of strings")
        if "max_turns" in design and (
            not isinstance(design["max_turns"], int) or design["max_turns"] < 1
        ):
            errors.append("design.max_turns must be an integer >= 1")
    if errors:
        return errors, warnings

    experiment = cfg["experiment"]
    if experiment not in EXPERIMENTS:
        errors.append(f"experiment must be one of {EXPERIMENTS}, got {experiment!r}")
    status = cfg["status"]
    if status not in STATUSES:
        errors.append(f"status must be one of {STATUSES}, got {status!r}")
    behavioral = experiment in BEHAVIORAL

    env_model = (cfg.get("environment") or {}).get("model", "")
    if not env_model:
        errors.append("environment.model is required")

    # --- judge panel: doctrine D6, exactly-3-seat family-diverse panel ---------------------
    judges = _judge_specs(cfg)
    if len(judges) < 3:
        errors.append(f"judge panel needs >= 3 seats (doctrine D6), got {len(judges)}")
    keys = [j.key for j in judges]
    if len(set(keys)) != len(keys):
        errors.append(f"judge keys must be unique, got {keys}")
    families = {j.family for j in judges}
    bad_families = families - set(CANDIDATE_FAMILIES)
    if bad_families:
        errors.append(f"unknown judge families {sorted(bad_families)}, "
                      f"expected one of {CANDIDATE_FAMILIES}")
    if len(families) < 3:
        errors.append(f"judges must span >= 3 distinct families (correlated bias is the "
                      f"enemy), got {sorted(families)}")

    # Behavioral findings are only certified for the exact Exp 0 environment and ordered
    # judge seats. Role drift is a new instrument and must be re-certified, even in a draft.
    if behavioral and env_model != EXP0_ENV_MODEL:
        errors.append(f"behavioral environment must match certified environment "
                      f"{EXP0_ENV_MODEL!r}; role drift requires re-certification")
    if behavioral and _configured_panel(cfg) != _certified_panel():
        errors.append("behavioral judge panel must match the certified ordered panel exactly; "
                      "role drift requires re-certification")

    # --- subjects --------------------------------------------------------------------------
    subjects = cfg.get("subjects") or []
    if len(set(subjects)) != len(subjects):
        errors.append("subjects contain duplicates")

    # --- structural separation: env != judge != subject (same gate the runtime enforces) ---
    if env_model and judges and subjects:
        try:
            assert_distinct(env_model, judges, subjects)
        except ValueError as e:
            errors.append(f"structural gate: {e}")

    # --- design ------------------------------------------------------------------------------
    design = cfg.get("design") or {}
    k = design.get("k")
    if not isinstance(k, int) or k < 1:
        errors.append(f"design.k must be an integer >= 1, got {k!r}")
    elif behavioral and k < 5:
        errors.append(f"design.k must be >= 5 for behavioral studies (prereg Tension 2: "
                      f"k=2 flipped ~30% of pilot cells), got {k}")
    registry = {c.challenge_id for c in load_challenges()}
    chosen = resolve_challenges(cfg)
    if not chosen:
        errors.append("design.challenges must be 'all' or a non-empty list of ids")
    unknown = [c for c in chosen if c not in registry]
    if unknown:
        errors.append(f"unknown challenge ids {unknown}, not in the frozen registry")
    if len(set(chosen)) != len(chosen):
        errors.append("design.challenges contains duplicates")
    if not unknown and chosen and set(chosen) != registry:
        warnings.append("challenge subset: the ambiguity gate was certified on the full "
                        "set; a subset study inherits it with a caveat")

    # --- blinding + exclusions: pre-registered discipline for behavioral studies -----------
    if behavioral and not (cfg.get("blinding") or {}).get("judges_blind_to_subject"):
        errors.append("blinding.judges_blind_to_subject must be true for behavioral "
                      "studies (doctrine D6)")
    exclusions = cfg.get("exclusions") or []
    if behavioral and not exclusions:
        errors.append("exclusions must be pre-registered (non-empty) for behavioral "
                      "studies, decided BEFORE any data")
    for ex in exclusions:
        action = ex.get("action")
        if action not in EXCLUSION_ACTIONS:
            errors.append(f"exclusion {ex.get('id', '?')}: action must be one of "
                          f"{EXCLUSION_ACTIONS}, got {action!r}")

    # --- certification precondition ---------------------------------------------------------
    require = (cfg.get("certification") or {}).get("require")
    if behavioral and require not in ("CERTIFIED", "CONDITIONALLY CERTIFIED"):
        errors.append("certification.require must be CERTIFIED or CONDITIONALLY CERTIFIED "
                      f"for behavioral studies, got {require!r}")

    # --- provenance pinning ------------------------------------------------------------------
    protocol = cfg.get("protocol") or {}
    rubric = protocol.get("rubric_version")
    if rubric is not None and rubric != RUBRIC_VERSION:
        errors.append(f"rubric_version {rubric!r} does not match the instrument's "
                      f"{RUBRIC_VERSION!r}; the rubric moved on, re-port the protocol")
    pinned = protocol.get("protocol_hash")
    live = protocol_hash()
    if status == "frozen":
        if not pinned:
            errors.append("frozen study must pin protocol.protocol_hash")
        elif pinned != live:
            errors.append(f"frozen protocol_hash {pinned} != live instrument hash {live}; "
                          "the instrument changed, re-certify before running")
    elif pinned and pinned != live:
        warnings.append(f"draft pins protocol_hash {pinned} but the live hash is {live}; "
                        "the pin will be refreshed at freeze")

    return errors, warnings


def _config_root(config_path: str | Path) -> Path:
    """Resolve relative artifact paths from the nearest project root, then the cwd."""
    path = Path(config_path).resolve()
    for parent in (path.parent, *path.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _certification_state(cfg: dict, config_path: str | Path) -> tuple[str, list[str]]:
    """Offline certification check. Returns (line for the plan, extra detail lines).

    Reads the Instrument Health verdict from certification.gates_file (written by
    ``exp0 health``); never recomputes it and never touches the network.
    """
    cert = cfg.get("certification") or {}
    require = cert.get("require")
    if cfg.get("experiment") == "exp0" or require is None:
        return "certification precondition: none (exp0 is what produces certification)", []
    gates_path = Path(cert.get("gates_file") or DEFAULT_GATES_FILE)
    if not gates_path.is_absolute():
        gates_path = _config_root(config_path) / gates_path
    if not gates_path.exists():
        return (f"certification: require >= {require} -> BLOCKED "
                f"(no gates file at {gates_path}; run `exp0 health`)"), []
    blocked_prefix = f"certification: require >= {require} -> BLOCKED"
    try:
        gates = json.loads(gates_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return blocked_prefix, [f"  - invalid gates file: {exc}"]
    if not isinstance(gates, dict):
        return blocked_prefix, ["  - invalid gates file: top level must be an object"]
    verdict = gates.get("verdict", "NOT CERTIFIED")
    raw_caveats = gates.get("caveats", [])
    if not isinstance(raw_caveats, list) or any(
        not isinstance(caveat, str) for caveat in raw_caveats
    ):
        return blocked_prefix, ["  - invalid gates file: caveats must be a list of strings"]
    caveats = list(raw_caveats)
    protocol = cfg.get("protocol") or {}
    expected_hash = protocol.get("protocol_hash") or protocol_hash()
    expected_rubric = protocol.get("rubric_version") or RUBRIC_VERSION
    provenance_errors = []
    if gates.get("protocol_hash") != expected_hash:
        provenance_errors.append(
            f"protocol mismatch: gates {gates.get('protocol_hash')!r}, expected {expected_hash!r}"
        )
    if gates.get("rubric") != expected_rubric:
        provenance_errors.append(
            f"rubric mismatch: gates {gates.get('rubric')!r}, expected {expected_rubric!r}"
        )
    if gates.get("certified_environment") != (cfg.get("environment") or {}).get("model"):
        provenance_errors.append("certified environment in gates does not match study config")
    if gates.get("certified_panel") != _configured_panel(cfg):
        provenance_errors.append("certified panel in gates does not match study config")

    manifest_digest = gates.get("source_manifest_sha256")
    if not isinstance(manifest_digest, str) or not _SHA256_RE.fullmatch(manifest_digest):
        provenance_errors.append("source_manifest_sha256 must be a 64-character SHA-256")
    elif manifest_digest != _REVIEWED_SOURCE_MANIFEST_SHA256:
        provenance_errors.append("source_manifest_sha256 does not match the reviewed packet")

    source_shards = gates.get("source_shards")
    if not isinstance(source_shards, dict) or set(source_shards) != set(
        _REVIEWED_SOURCE_SHARDS
    ):
        provenance_errors.append("source_shards must contain the exact reviewed shard set")
    else:
        for name, expected_digest in _REVIEWED_SOURCE_SHARDS.items():
            record = source_shards.get(name)
            digest = record.get("sha256") if isinstance(record, dict) else None
            if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                provenance_errors.append(f"source_shards.{name}.sha256 must be a SHA-256")
            elif digest != expected_digest:
                provenance_errors.append(f"source_shards.{name} does not match reviewed bytes")

    gate_rows = gates.get("gates")
    provenance_row = None
    if isinstance(gate_rows, list):
        provenance_row = next(
            (row for row in gate_rows
             if isinstance(row, dict) and row.get("gate") == "provenance"),
            None,
        )
    if gates.get("binding") != "collection-time" \
            or gates.get("collection_time_protocol_stamp") is not True \
            or not isinstance(provenance_row, dict) \
            or provenance_row.get("status") != "PASS":
        provenance_errors.append("collection-time provenance must be present and PASS")
    # The only reviewed packet in v0.2 is retrospective. A future collection-time run must
    # update these trusted release constants before any behavioral plan can become runnable.
    provenance_errors.append(
        "this release has no trusted collection-time provenance; the initial run is retrospective"
    )
    ok = (
        not provenance_errors
        and VERDICT_RANK.get(verdict, 0) >= VERDICT_RANK.get(require, 2)
    )
    state = "RUNNABLE" if ok else "BLOCKED"
    line = f"certification: require >= {require}, measured {verdict} -> {state}"
    return line, [f"  - {item}" for item in [*provenance_errors, *caveats]]


def render_plan(cfg: dict, config_path: str | Path) -> str:
    """The dry-run execution plan: what a real run WOULD do, with zero model API calls."""
    subjects = cfg.get("subjects") or []
    judges = _judge_specs(cfg)
    challenges = resolve_challenges(cfg)
    k = (cfg.get("design") or {}).get("k", 0)
    max_turns = (cfg.get("design") or {}).get("max_turns", DEFAULT_MAX_TURNS)
    conversations = len(subjects) * len(challenges) * k
    judge_calls = conversations * len(judges)
    floor_env = 2 * len(challenges)               # accept-fix + reject-trap per challenge
    floor_judge = 2 * len(challenges) * len(judges)
    pinned = (cfg.get("protocol") or {}).get("protocol_hash")
    hash_note = ("matches config" if pinned == protocol_hash()
                 else "config unpinned (draft)" if not pinned
                 else f"STALE, config pins {pinned}")
    cert_line, cert_detail = _certification_state(cfg, config_path)
    anchor = sum(1 for c in challenges if c in EXECUTION_ANCHORED)

    lines = [
        f"STUDY PLAN, {cfg.get('study_id')} ({cfg.get('experiment')}, {cfg.get('status')})",
        f"  config .............. {config_path}",
        f"  instrument hash ..... {protocol_hash()} [{hash_note}] · rubric {RUBRIC_VERSION}",
        f"  {cert_line}",
        *cert_detail,
        f"  environment ......... {(cfg.get('environment') or {}).get('model')}",
        "  judges .............. " + " · ".join(f"{j.key}={j.model} ({j.family})"
                                                for j in judges),
        f"  subjects ............ {len(subjects)}",
        f"  challenges .......... {len(challenges)} "
        f"({anchor} execution-anchored, {len(challenges) - anchor} human-anchored)",
        f"  grid ................ {len(subjects)} subjects x {len(challenges)} challenges "
        f"x k={k} = {conversations} conversations",
        f"  judge calls ......... {conversations} x {len(judges)} judges = {judge_calls}",
        f"  floor gate first .... {floor_env} env + {floor_judge} judge calls "
        "(any failure aborts, exclusion E3)",
        f"  env call ceiling .... {conversations} x max_turns {max_turns} = "
        f"{conversations * max_turns}",
        "  execution order ..... 1) exp0 floor  2) exp0-style panel sweep bound to this "
        "config (wired post-certification)",
        "  DRY RUN: no model API was called.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2 or args[0] not in ("validate", "plan"):
        raise SystemExit("usage: python -m model_familiarity.study "
                         "<validate|plan> <config.yaml>")
    sub, path = args[0], args[1]
    cfg = load_config(path)
    errors, warnings = validate_config(cfg)
    for w in warnings:
        print(f"WARN: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise SystemExit(1)
    if sub == "validate":
        print(f"OK: {cfg.get('study_id')} valid ({len(warnings)} warning(s))")
        return
    print(render_plan(cfg, path))


if __name__ == "__main__":
    main()
