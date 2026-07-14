"""Study-config layer (study.py), pure-logic tests, no network.

Covers the YAML schema validation (required fields, vocabularies), the structural
env!=judge!=subject gate as seen from a config, the D6 family-diversity rule, the k>=5
behavioral lock, pre-registered exclusions, frozen-hash pinning, the offline certification
precondition, and the dry-run planner's arithmetic. Every test is offline by construction:
study.py never constructs a provider.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from model_familiarity.instrument_health import RUBRIC_VERSION, protocol_hash
from model_familiarity.panel import DEFAULT_PANEL, EXP0_ENV_MODEL
from model_familiarity.study import (
    _REVIEWED_SOURCE_MANIFEST_SHA256,
    _REVIEWED_SOURCE_SHARDS,
    load_config,
    main,
    render_plan,
    resolve_challenges,
    validate_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "study_configs"
SHIPPED = Path(__file__).parents[1] / "configs" / "studies" / "example-behavioral-study.yaml"


@pytest.fixture()
def valid() -> dict:
    return load_config(FIXTURES / "valid-draft.yaml")


def _errors(cfg: dict) -> list[str]:
    errors, _ = validate_config(cfg)
    return errors


def _gate_packet(verdict: str, caveats: list[str] | None = None) -> dict:
    return {
        "protocol_hash": protocol_hash(),
        "rubric": RUBRIC_VERSION,
        "certified_environment": EXP0_ENV_MODEL,
        "certified_panel": [
            {"key": judge.key, "model": judge.model, "family": judge.family,
             "provider_key": judge.provider_key}
            for judge in DEFAULT_PANEL
        ],
        "verdict": verdict,
        "caveats": caveats or [],
        "binding": "collection-time",
        "collection_time_protocol_stamp": True,
        "source_manifest_sha256": _REVIEWED_SOURCE_MANIFEST_SHA256,
        "source_shards": {
            name: {"sha256": digest} for name, digest in _REVIEWED_SOURCE_SHARDS.items()
        },
        "gates": [{"gate": "provenance", "status": "PASS"}],
    }


# --- the shipped config and the valid fixture must both pass -------------------------------

def test_valid_fixture_passes(valid):
    errors, warnings = validate_config(valid)
    assert errors == []
    assert warnings == []


def test_shipped_exp1_config_passes():
    cfg = load_config(SHIPPED)
    errors, warnings = validate_config(cfg)
    assert errors == []
    assert warnings == []
    # the shipped port must stay draft until certification + review freeze it
    assert cfg["status"] == "draft"
    assert cfg["design"]["k"] >= 5


def test_challenges_all_resolves_to_full_registry(valid):
    assert len(resolve_challenges(valid)) == 8


# --- structural gates -----------------------------------------------------------------------

def test_env_as_judge_rejected():
    cfg = load_config(FIXTURES / "invalid-env-is-judge.yaml")
    assert any("structural gate" in e and "also a judge" in e for e in _errors(cfg))


def test_unknown_challenge_rejected():
    cfg = load_config(FIXTURES / "invalid-unknown-challenge.yaml")
    assert any("totally_made_up_challenge" in e for e in _errors(cfg))


def test_subject_overlapping_judge_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["subjects"].append(cfg["judges"][0]["model"])
    assert any("cannot grade itself" in e for e in _errors(cfg))


def test_env_as_subject_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["subjects"].append(cfg["environment"]["model"])
    assert any("env must be held out" in e for e in _errors(cfg))


def test_duplicate_subjects_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["subjects"].append(cfg["subjects"][0])
    assert any("duplicates" in e for e in _errors(cfg))


# --- judge panel: doctrine D6 ----------------------------------------------------------------

def test_two_judges_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["judges"] = cfg["judges"][:2]
    assert any(">= 3 seats" in e for e in _errors(cfg))


def test_judges_must_span_three_families(valid):
    cfg = copy.deepcopy(valid)
    cfg["judges"][2]["family"] = "open"  # now open/anthropic/open
    assert any("3 distinct families" in e for e in _errors(cfg))


def test_unknown_family_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["judges"][0]["family"] = "martian"
    assert any("unknown judge families" in e for e in _errors(cfg))


def test_duplicate_judge_keys_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["judges"][1]["key"] = "judge_a"
    assert any("keys must be unique" in e for e in _errors(cfg))


@pytest.mark.parametrize("field", ["key", "model", "family", "provider"])
def test_behavioral_judge_role_drift_requires_recertification(valid, field):
    cfg = copy.deepcopy(valid)
    cfg["judges"][0][field] = "changed"
    assert any("certified ordered panel" in error for error in _errors(cfg))


def test_behavioral_environment_drift_requires_recertification(valid):
    cfg = copy.deepcopy(valid)
    cfg["environment"]["model"] = "changed"
    assert any("certified environment" in error for error in _errors(cfg))


# --- schema + vocabularies -------------------------------------------------------------------

@pytest.mark.parametrize("field", ["study_id", "experiment", "status", "environment",
                                   "judges", "subjects", "design"])
def test_missing_required_field(valid, field):
    cfg = copy.deepcopy(valid)
    del cfg[field]
    assert any(f"missing required field: {field}" in e for e in _errors(cfg))


def test_bad_experiment_value(valid):
    cfg = copy.deepcopy(valid)
    cfg["experiment"] = "exp9"
    assert any("experiment must be one of" in e for e in _errors(cfg))


def test_bad_status_value(valid):
    cfg = copy.deepcopy(valid)
    cfg["status"] = "running"
    assert any("status must be one of" in e for e in _errors(cfg))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("environment", "not-a-map", "environment must be a mapping"),
        ("judges", "not-a-list", "judges must be a list"),
        ("subjects", {"model": "x"}, "subjects must be a list"),
        ("design", ["not-a-map"], "design must be a mapping"),
        ("exclusions", [None], "every exclusions entry must be a mapping"),
        ("environment", {"model": ["not-a-string"]}, "environment.model must be a string"),
        ("design", {"k": 5, "challenges": [{}]},
         "design.challenges must be 'all' or a list of strings"),
    ],
)
def test_malformed_config_shapes_return_errors(valid, field, value, message):
    cfg = copy.deepcopy(valid)
    cfg[field] = value
    assert message in _errors(cfg)


def test_malformed_judge_field_returns_error(valid):
    cfg = copy.deepcopy(valid)
    cfg["judges"][0]["model"] = ["not-a-string"]
    assert "judges[0].model must be a string" in _errors(cfg)


# --- behavioral-study locks (prereg discipline) ---------------------------------------------

def test_k_below_five_rejected_for_behavioral(valid):
    cfg = copy.deepcopy(valid)
    cfg["design"]["k"] = 2
    assert any("k must be >= 5 for behavioral" in e for e in _errors(cfg))


def test_k_below_five_allowed_for_exp0(valid):
    cfg = copy.deepcopy(valid)
    cfg["experiment"] = "exp0"
    cfg["design"]["k"] = 2
    cfg["certification"]["require"] = None
    assert _errors(cfg) == []


def test_k_zero_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["design"]["k"] = 0
    assert any("integer >= 1" in e for e in _errors(cfg))


def test_blinding_required_for_behavioral(valid):
    cfg = copy.deepcopy(valid)
    cfg["blinding"]["judges_blind_to_subject"] = False
    assert any("judges_blind_to_subject must be true" in e for e in _errors(cfg))


def test_exclusions_required_for_behavioral(valid):
    cfg = copy.deepcopy(valid)
    cfg["exclusions"] = []
    assert any("exclusions must be pre-registered" in e for e in _errors(cfg))


def test_exclusion_action_vocabulary(valid):
    cfg = copy.deepcopy(valid)
    cfg["exclusions"][0]["action"] = "ignore"
    assert any("action must be one of" in e for e in _errors(cfg))


def test_certification_require_needed_for_behavioral(valid):
    cfg = copy.deepcopy(valid)
    cfg["certification"]["require"] = None
    assert any("certification.require" in e for e in _errors(cfg))


# --- provenance pinning -----------------------------------------------------------------------

def test_frozen_requires_hash(valid):
    cfg = copy.deepcopy(valid)
    cfg["status"] = "frozen"
    assert any("must pin protocol.protocol_hash" in e for e in _errors(cfg))


def test_frozen_hash_must_match_live(valid):
    cfg = copy.deepcopy(valid)
    cfg["status"] = "frozen"
    cfg["protocol"]["protocol_hash"] = "deadbeefdeadbeef"
    assert any("re-certify" in e for e in _errors(cfg))


def test_frozen_with_live_hash_passes(valid):
    cfg = copy.deepcopy(valid)
    cfg["status"] = "frozen"
    cfg["protocol"]["protocol_hash"] = protocol_hash()
    assert _errors(cfg) == []


def test_stale_draft_hash_warns_not_errors(valid):
    cfg = copy.deepcopy(valid)
    cfg["protocol"]["protocol_hash"] = "deadbeefdeadbeef"
    errors, warnings = validate_config(cfg)
    assert errors == []
    assert any("refreshed at freeze" in w for w in warnings)


def test_rubric_version_mismatch_rejected(valid):
    cfg = copy.deepcopy(valid)
    cfg["protocol"]["rubric_version"] = "lhcr-rubric-v99"
    assert any(RUBRIC_VERSION in e for e in _errors(cfg))


def test_challenge_subset_warns(valid):
    cfg = copy.deepcopy(valid)
    cfg["design"]["challenges"] = ["reset_specificity_override"]
    errors, warnings = validate_config(cfg)
    assert errors == []
    assert any("subset" in w for w in warnings)


# --- the dry-run planner ----------------------------------------------------------------------

def test_plan_arithmetic_for_shipped_config():
    cfg = load_config(SHIPPED)
    plan = render_plan(cfg, SHIPPED)
    # 12 subjects x 8 challenges x k=5 = 480 conversations, x 3 judges = 1440 judge calls
    assert "= 480 conversations" in plan
    assert "480 x 3 judges = 1440" in plan
    assert "16 env + 48 judge calls" in plan
    assert "DRY RUN: no model API was called." in plan


def test_plan_shows_current_instrument_hash(valid):
    plan = render_plan(valid, "x.yaml")
    assert protocol_hash() in plan
    assert "config unpinned (draft)" in plan


def test_plan_blocked_when_not_certified(valid, tmp_path):
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps(_gate_packet(
        "NOT CERTIFIED", ["FAILED: blind leakage (provider-guess)"]
    )))
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "blind leakage" in plan


def test_plan_blocks_certified_packet_until_collection_time_run_is_trusted(valid, tmp_path):
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps(_gate_packet("CERTIFIED")))
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "no trusted collection-time provenance" in plan


def test_plan_conditional_still_blocks_without_trusted_collection_provenance(valid, tmp_path):
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps(_gate_packet(
        "CONDITIONALLY CERTIFIED", ["PENDING (auxiliary): human-anchor agreement"]
    )))
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "no trusted collection-time provenance" in plan
    assert "human-anchor" in plan


def test_plan_blocked_when_gates_file_missing(valid):
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = "results/does/not/exist/gates.json"
    assert "-> BLOCKED" in render_plan(cfg, "x.yaml")


def test_plan_blocks_certified_packet_with_wrong_protocol_hash(valid, tmp_path):
    gates = tmp_path / "gates.json"
    packet = _gate_packet("CERTIFIED")
    packet["protocol_hash"] = "deadbeefdeadbeef"
    gates.write_text(json.dumps(packet))
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "protocol mismatch" in plan


def test_plan_blocks_certified_packet_with_wrong_rubric(valid, tmp_path):
    gates = tmp_path / "gates.json"
    packet = _gate_packet("CERTIFIED")
    packet["rubric"] = "lhcr-rubric-v0"
    gates.write_text(json.dumps(packet))
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "rubric mismatch" in plan


@pytest.mark.parametrize("mutation", ["missing_manifest", "fake_manifest", "missing_shard",
                                      "fake_shard", "no_collection_stamp", "no_gate_pass"])
def test_plan_blocks_missing_or_fake_source_provenance(valid, tmp_path, mutation):
    packet = _gate_packet("CERTIFIED")
    if mutation == "missing_manifest":
        del packet["source_manifest_sha256"]
    elif mutation == "fake_manifest":
        packet["source_manifest_sha256"] = "0" * 64
    elif mutation == "missing_shard":
        packet["source_shards"].pop("floor.json")
    elif mutation == "fake_shard":
        packet["source_shards"]["floor.json"]["sha256"] = "0" * 64
    elif mutation == "no_collection_stamp":
        packet["binding"] = "retrospective"
        packet["collection_time_protocol_stamp"] = False
    else:
        packet["gates"][0]["status"] = "FAIL"
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps(packet))
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "provenance" in plan or "source_" in plan


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"verdict":', "invalid gates file"),
        ("[]", "top level must be an object"),
        ('{"caveats": "not-a-list"}', "caveats must be a list of strings"),
    ],
)
def test_plan_blocks_malformed_certification_packet(valid, tmp_path, payload, message):
    gates = tmp_path / "gates.json"
    gates.write_text(payload)
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert message in plan


def test_plan_blocks_unreadable_certification_packet(valid, tmp_path, monkeypatch):
    gates = tmp_path / "gates.json"
    gates.write_text("{}")
    cfg = copy.deepcopy(valid)
    cfg["certification"]["gates_file"] = str(gates)
    original = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == gates:
            raise OSError("permission denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    plan = render_plan(cfg, "x.yaml")
    assert "-> BLOCKED" in plan
    assert "permission denied" in plan


def test_exp0_plan_needs_no_certification(valid):
    cfg = copy.deepcopy(valid)
    cfg["experiment"] = "exp0"
    cfg["certification"]["require"] = None
    plan = render_plan(cfg, "x.yaml")
    assert "none (exp0 is what produces certification)" in plan


# --- the CLI ------------------------------------------------------------------------------------

def test_cli_validate_ok(capsys):
    main(["validate", str(FIXTURES / "valid-draft.yaml")])
    assert "OK: fixture-valid-draft valid" in capsys.readouterr().out


def test_cli_validate_invalid_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["validate", str(FIXTURES / "invalid-env-is-judge.yaml")])
    assert exc.value.code == 1
    assert "ERROR:" in capsys.readouterr().out


def test_cli_plan_prints_dry_run(capsys):
    main(["plan", str(SHIPPED)])
    assert "DRY RUN: no model API was called." in capsys.readouterr().out


def test_cli_usage_on_bad_args():
    with pytest.raises(SystemExit, match="usage"):
        main(["frobnicate"])
