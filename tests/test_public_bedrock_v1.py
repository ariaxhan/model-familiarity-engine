"""Contract tests for the standalone public Bedrock evidence runner."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from experiments import public_bedrock_v1 as experiment
from model_familiarity.providers.base import LLMResponse
from model_familiarity.tasks import get_task


class FakeProvider:
    name = "fake"

    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies or [])
        self.calls = 0

    async def complete(self, model, system_prompt, user_prompt, max_tokens=1024, temperature=0):
        self.calls += 1
        content = self.replies.pop(0)
        return LLMResponse(
            content=content,
            latency_ms=1.0,
            tokens_used=10,
            model=model,
            input_tokens=8,
            output_tokens=2,
        )

    async def list_models(self):
        return []

    async def is_available(self):
        return True


def test_full_rejects_k_below_five_and_accepts_five():
    with pytest.raises(ValueError, match="k >= 5"):
        experiment.build_plan("full", [experiment.DEFAULT_MODELS[0]], k=4)
    assert experiment.build_plan("full", [experiment.DEFAULT_MODELS[0]], k=5).k == 5


@pytest.mark.parametrize("models", [[], [""], ["   "], ["x", "x"]])
def test_invalid_or_empty_model_roster_rejected(models):
    with pytest.raises(ValueError, match="model roster"):
        experiment.build_plan("full", models, k=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        '{"reached":true,"divergence":"equivalent","how":"plain"}',
        '```json\n{"reached":true,"divergence":"equivalent","how":"fenced"}\n```',
        'Verdict follows: {"reached":true,"divergence":"equivalent","how":"wrapped"}.',
    ],
)
async def test_strict_judge_accepts_one_valid_object_with_harmless_wrapper(reply):
    verdict = await experiment.strict_judge(
        get_task("ios_zoom"), "not blank", FakeProvider([reply]), experiment.JUDGE_MODEL
    )
    assert verdict["reached"] is True
    assert verdict["divergence"] == "equivalent"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "code"),
    [
        ("no object here", "no_object"),
        (
            '{"reached":true,"divergence":"equivalent"} '
            '{"reached":false,"divergence":"worse"}',
            "multiple_objects",
        ),
        ('{"reached":"false","divergence":"worse","how":"x"}', "invalid_boolean"),
        ('{"reached":false,"divergence":"close","how":"x"}', "invalid_divergence"),
        ('{"reached":false,"divergence":"equivalent","how":"x"}', "contradiction"),
    ],
)
async def test_strict_judge_rejects_unsafe_or_invalid_verdicts_with_safe_code(reply, code):
    task = get_task("ios_zoom")
    with pytest.raises(experiment.StrictVerdictError) as raised:
        await experiment.strict_judge(
            task, "not blank", FakeProvider([reply]), experiment.JUDGE_MODEL
        )
    assert raised.value.code == code
    assert reply not in str(raised.value)


@pytest.mark.asyncio
async def test_subject_judge_failure_preserves_safe_subject_evidence(monkeypatch):
    async def fake_replay(*args, **kwargs):
        return SimpleNamespace(
            output="The input must use a 16px font to stop iOS zoom.",
            latency_ms=12.5,
            input_tokens=31,
            output_tokens=14,
            cost_usd=0.0001,
        )

    monkeypatch.setattr("model_familiarity.replay.replay_task", fake_replay)
    provider = FakeProvider(['{"reached":"true","divergence":"equivalent","how":"x"}'])
    plan = experiment.build_plan("smoke", [experiment.DEFAULT_MODELS[0]], k=1)
    records = await experiment._run_subjects(provider, plan)
    assert len(records) == 1
    record = records[0]
    assert record["status"] == "error"
    assert record["error_kind"] == "strict_verdict_error/invalid_boolean"
    assert record["output"].startswith("The input")
    assert record["input_tokens"] == 31
    assert record["output_tokens"] == 14
    assert record["latency_ms"] == 12.5
    assert "raw" not in record


@pytest.mark.asyncio
async def test_blank_output_is_miss_without_judge_call():
    provider = FakeProvider([])
    verdict = await experiment.strict_judge(
        get_task("ios_zoom"), " \n ", provider, experiment.JUDGE_MODEL
    )
    assert verdict["reached"] is False
    assert verdict["divergence"] == "worse"
    assert verdict["judge_called"] is False
    assert provider.calls == 0


def test_empty_evidence_and_partial_cells_are_not_publishable():
    plan = experiment.build_plan("full", [experiment.DEFAULT_MODELS[0]], k=5)
    empty = experiment.aggregate_records([], plan, floor_passed=True)
    assert empty["publishable"] is False
    assert empty["tie_out"]["expected_subject_attempts"] == 30

    partial = [
        experiment.subject_record(
            model=plan.models[0],
            task_id="ios_zoom",
            condition="cold",
            sample_index=i,
            reached=True,
        )
        for i in range(1, 6)
    ]
    aggregate = experiment.aggregate_records(partial, plan, floor_passed=True)
    assert aggregate["publishable"] is False
    assert aggregate["tie_out"]["completed_subject_attempts"] == 5
    assert aggregate["tie_out"]["missing_subject_attempts"] == 25


def test_wilson_interval_boundaries():
    assert experiment.wilson_interval(0, 0) == (0.0, 1.0)
    fail_low, fail_high = experiment.wilson_interval(0, 5)
    pass_low, pass_high = experiment.wilson_interval(5, 5)
    assert fail_low == 0.0
    assert 0.0 < fail_high < 1.0
    assert 0.0 < pass_low < 1.0
    assert pass_high == 1.0


def test_manifest_checksums_are_deterministic_and_counts_tie_out(tmp_path):
    plan = experiment.build_plan("smoke", [experiment.DEFAULT_MODELS[0]], k=1)
    records = [
        experiment.subject_record(
            model=plan.models[0],
            task_id="ios_zoom",
            condition="cold",
            sample_index=1,
            reached=False,
        )
    ]
    packet = experiment.write_immutable_packet(
        tmp_path,
        "fixed-run",
        plan,
        records,
        floor_passed=True,
        created_at="2026-07-14T00:00:00Z",
        code_revision="abc123",
    )
    manifest = json.loads((packet / "manifest.json").read_text())
    assert manifest["tie_out"]["record_count"] == 1
    assert len(manifest["protocol"]["protocol_sha256"]) == 64
    assert set(manifest["protocol"]["task_sha256"]) == set(experiment.PUBLIC_TASK_IDS)
    assert manifest["files"] == sorted(manifest["files"], key=lambda item: item["path"])
    assert all(
        item["sha256"] == experiment.sha256_file(packet / item["path"])
        for item in manifest["files"]
    )


def test_existing_run_is_never_overwritten(tmp_path):
    plan = experiment.build_plan("smoke", [experiment.DEFAULT_MODELS[0]], k=1)
    kwargs = dict(
        output_root=tmp_path,
        run_id="same-run",
        plan=plan,
        records=[],
        floor_passed=False,
        created_at="2026-07-14T00:00:00Z",
        code_revision="unknown",
    )
    experiment.write_immutable_packet(**kwargs)
    with pytest.raises(FileExistsError, match="immutable run already exists"):
        experiment.write_immutable_packet(**kwargs)


def test_public_export_requires_publishable_packet_and_is_immutable(tmp_path):
    plan = experiment.build_plan("full", [experiment.DEFAULT_MODELS[0]], k=5)
    floor = [
        {
            "schema": "public-bedrock-v1/evidence",
            "phase": "floor",
            "attempt_id": f"floor/{index}",
            "status": "complete",
            "passed": True,
            "agrees_with_spine": True,
        }
        for index in range(experiment.FLOOR_PROBE_COUNT * experiment.FLOOR_REPETITIONS)
    ]
    subjects = [
        experiment.subject_record(
            model=plan.models[0],
            task_id=task_id,
            condition=condition,
            sample_index=sample_index,
            reached=True,
        )
        for task_id in plan.task_ids
        for condition in plan.conditions
        for sample_index in range(1, 6)
    ]
    packet = experiment.write_immutable_packet(
        tmp_path / "raw",
        "publishable-run",
        plan,
        [*floor, *subjects],
        floor_passed=True,
        created_at="2026-07-14T00:00:00Z",
        code_revision="abc123",
    )
    public = experiment.export_publishable(packet, tmp_path / "public")
    assert (public / "summary.json").is_file()
    assert (public / "publication.json").is_file()
    assert list((public / "model-cards").glob("*.md"))
    assert not (public / "evidence.jsonl").exists()
    with pytest.raises(FileExistsError, match="immutable public export"):
        experiment.export_publishable(packet, tmp_path / "public")

    smoke = experiment.build_plan("smoke", [experiment.DEFAULT_MODELS[0]], k=1)
    nonpublishable = experiment.write_immutable_packet(
        tmp_path / "raw",
        "nonpublishable-run",
        smoke,
        [],
        floor_passed=False,
        created_at="2026-07-14T00:00:00Z",
        code_revision="abc123",
    )
    with pytest.raises(ValueError, match="publishable full packet"):
        experiment.export_publishable(nonpublishable, tmp_path / "public")


def test_dry_run_makes_zero_provider_calls_or_artifacts(tmp_path, capsys):
    calls = 0

    def exploding_factory(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("dry-run constructed a provider")

    output_root = tmp_path / "must-not-exist"
    exit_code = experiment.run_cli(
        ["dry-run", "--output-root", str(output_root)], provider_factory=exploding_factory
    )
    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert calls == 0
    assert not output_root.exists()
    assert "planned calls" in stdout
    assert "projected maximum cost" in stdout
    assert "USD 5.00" in stdout


def test_projected_cost_ceiling_is_enforced():
    with pytest.raises(ValueError, match="projected maximum cost"):
        experiment.build_plan(
            "full", experiment.DEFAULT_MODELS, k=100, budget_usd=experiment.MAX_BUDGET_USD
        )


def test_model_card_is_narrow_and_names_limitations():
    plan = experiment.build_plan("smoke", [experiment.DEFAULT_MODELS[0]], k=1)
    summary = experiment.aggregate_records([], plan, floor_passed=False)
    card = experiment.render_model_card(plan.models[0], plan, summary, "2026-07-14")
    assert "three public synthetic debugging tasks" in card
    assert "not a broad model ranking" in card
    assert experiment.JUDGE_MODEL in card
