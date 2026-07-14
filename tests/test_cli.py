from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from model_familiarity.cli import CostGuardProvider, main
from model_familiarity.providers.base import LLMResponse, SafetyLimitError
from model_familiarity.study import load_config


def test_cli_help_lists_offline_surfaces():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "health" in result.output and "study" in result.output and "run" in result.output


def test_health_prints_not_certified_provenance_and_pending_gates():
    result = CliRunner().invoke(main, ["health"])
    assert result.exit_code == 0
    assert "NOT CERTIFIED" in result.output
    assert "FAILED: provenance" in result.output
    assert "human-anchor agreement" in result.output
    assert "oracle false-negative rate" in result.output


def test_live_run_defaults_to_zero_call_dry_run():
    result = CliRunner().invoke(main, ["run", "--model", "example-model"])
    assert result.exit_code == 0
    assert "provider-call ceiling  20" in result.output
    assert "DRY RUN: no model API was called." in result.output


def test_live_run_rejects_missing_confirmation_before_provider_creation():
    result = CliRunner().invoke(
        main,
        ["run", "--model", "example-model", "--execute", "--cost-ceiling-usd", "1"],
    )
    assert result.exit_code != 0
    assert "--confirm LIVE-RUN-WITH-BILLING" in result.output


def test_live_run_rejects_missing_cost_ceiling_before_provider_creation():
    result = CliRunner().invoke(
        main,
        [
            "run",
            "--model",
            "example-model",
            "--execute",
            "--confirm",
            "LIVE-RUN-WITH-BILLING",
        ],
    )
    assert result.exit_code != 0
    assert "--cost-ceiling-usd" in result.output


def test_study_example_is_available_outside_the_repository():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["study", "example"])
        assert result.exit_code == 0
        example = Path("example-behavioral-study.yaml")
        assert example.exists()
        assert "study_id: exp1-model-behavior" in example.read_text()


def test_study_validate_reports_malformed_yaml_cleanly():
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("broken.yaml").write_text("study_id: [unterminated")
        result = runner.invoke(main, ["study", "validate", "broken.yaml"])
        assert result.exit_code != 0
        assert "cannot read study config" in result.output
        assert "Traceback" not in result.output


def test_study_plan_blocks_truncated_gates_without_traceback(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "study_configs" / "valid-draft.yaml"
    cfg = load_config(fixture)
    gates = tmp_path / "gates.json"
    gates.write_text('{"verdict":')
    cfg["certification"]["gates_file"] = str(gates)
    config = tmp_path / "study.yaml"
    config.write_text(yaml.safe_dump(cfg))
    result = CliRunner().invoke(main, ["study", "plan", str(config)])
    assert result.exit_code == 0
    assert "-> BLOCKED" in result.output
    assert "invalid gates file" in result.output
    assert "Traceback" not in result.output


def test_live_execution_rejects_concurrency_before_provider_creation(monkeypatch):
    monkeypatch.setattr(
        "model_familiarity.cli.get_provider",
        lambda name: pytest.fail("provider must not be created"),
    )
    result = CliRunner().invoke(
        main,
        ["run", "--model", "example-model", "--execute", "--confirm",
         "LIVE-RUN-WITH-BILLING", "--cost-ceiling-usd", "1", "--concurrency", "2"],
    )
    assert result.exit_code != 0
    assert "requires --concurrency 1" in result.output


def test_live_run_cost_abort_is_nonzero_and_uses_requested_output(monkeypatch, tmp_path):
    class Provider:
        name = "fake"

    output = tmp_path / "run-output"
    seen = {}

    async def aborting_run(**kwargs):
        seen.update(kwargs)
        raise SafetyLimitError("ceiling crossed")

    monkeypatch.setattr("model_familiarity.cli.get_provider", lambda name: Provider())
    monkeypatch.setattr("model_familiarity.cli.run_pilot", aborting_run)
    result = CliRunner().invoke(
        main,
        ["run", "--model", "example-model", "--execute", "--confirm",
         "LIVE-RUN-WITH-BILLING", "--cost-ceiling-usd", "1", "--output-dir", str(output)],
    )
    assert result.exit_code != 0
    assert "LIVE RUN ABORTED: ceiling crossed" in result.output
    assert output.is_dir()
    assert seen["output_dir"] == output.resolve()


def test_unknown_price_requires_explicit_disable_flag():
    class Provider:
        name = "fake"

    guard = CostGuardProvider(Provider(), 1.0, False)
    response = LLMResponse("ok", 1.0, 1, "model", cost_usd=None)
    with pytest.raises(SafetyLimitError, match="cost enforcement cannot continue"):
        guard._record(response)
