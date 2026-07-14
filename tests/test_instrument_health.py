from __future__ import annotations

import json
from dataclasses import replace

import pytest

from model_familiarity import instrument_health as ih


def test_protocol_hash_is_stable_and_nonempty():
    assert ih.protocol_hash() == ih.protocol_hash()
    assert len(ih.protocol_hash()) == 16
    assert ih.protocol_hash() == "d5eef7a1a99bccee"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("challenge_id", "changed-id"),
        ("capability", "changed capability"),
        ("initial_prompt", "changed prompt"),
        ("followups", ["changed follow-up"]),
        ("known_outcome", "changed outcome"),
        ("layer_sequence", ["changed layer"]),
        ("trap", "changed trap"),
        ("source_episode", "changed source"),
        ("notes", "changed notes"),
        ("code_context", {"changed.txt": "changed code"}),
        ("fix_summary", "changed fix"),
        ("probes", [{"ask": "changed", "observation": "changed"}]),
        ("_extra", {"changed": True}),
    ],
)
def test_protocol_hash_changes_for_every_challenge_field(monkeypatch, field, value):
    original = ih.load_challenges()
    baseline = ih.protocol_hash()
    monkeypatch.setattr(
        ih,
        "load_challenges",
        lambda: [replace(original[0], **{field: value}), *original[1:]],
    )
    assert ih.protocol_hash() != baseline


def test_protocol_hash_changes_for_same_identity_closure_mutation(monkeypatch):
    original = ih.load_challenges()

    def factory(token: str):
        def spine(output: str) -> tuple[bool, str]:
            return token in output, token

        return spine

    first = factory("first")
    second = factory("second")
    first.__module__ = second.__module__ = "public.spines"
    first.__qualname__ = second.__qualname__ = "shared_spine"
    current = first
    monkeypatch.setattr(
        ih,
        "load_challenges",
        lambda: [replace(original[0], spine=current), *original[1:]],
    )
    first_hash = ih.protocol_hash()
    current = second
    assert ih.protocol_hash() != first_hash


def test_protocol_hash_changes_for_same_identity_body_mutation(monkeypatch):
    original = ih.load_challenges()
    baseline = ih.protocol_hash()

    def changed_spine(_output: str) -> tuple[bool, str]:
        return True, "changed semantics"

    changed_spine.__module__ = original[0].spine.__module__
    changed_spine.__qualname__ = original[0].spine.__qualname__
    monkeypatch.setattr(
        ih,
        "load_challenges",
        lambda: [replace(original[0], spine=changed_spine), *original[1:]],
    )
    assert ih.protocol_hash() != baseline


def test_blind_gate_exact_registered_boundary_passes(monkeypatch):
    rows = []
    for index in range(20):
        guesses = {
            judge.key: {
                "parse_ok": True,
                "family": "open" if index < 8 else "anthropic",
            }
            for judge in ih.DEFAULT_PANEL
        }
        rows.append({"true_family": "open", "guesses": guesses})
    monkeypatch.setattr(
        ih,
        "_load",
        lambda name: {"chance": 0.25, "rows": rows} if name == "blind.json" else None,
    )
    assert ih._gate_blind()["status"] == ih.PASS


def test_public_provenance_gate_fails_closed():
    gate = ih._gate_provenance()
    assert gate["status"] == ih.FAIL
    assert gate["value"] == "retrospective only"


def test_published_gate_packet_is_not_certified_with_named_caveats():
    packet = ih._load("gates.json")
    assert packet["verdict"] == "NOT CERTIFIED"
    assert set(packet["caveats"]) == {
        "FAILED: provenance",
        "PENDING (auxiliary): oracle false-negative rate",
        "PENDING (auxiliary): human-anchor agreement",
    }


def test_human_anchor_two_judge_tie_is_not_coerced(monkeypatch, tmp_path):
    (tmp_path / "answer-key.json").write_text(json.dumps({
        "p1": {"panel": {"a": {"reached": True}, "b": {"reached": False}}}
    }))
    (tmp_path / "scoring-sheet-filled.csv").write_text("packet_id,reached(y/n)\np1,y\n")
    monkeypatch.setattr(ih.layout, "EXP0_HUMAN", tmp_path)
    gate = ih._gate_human([])
    assert gate["status"] == ih.PENDING
    assert "tied" in gate["detail"]


def test_human_anchor_scores_strict_majorities_and_drops_ties(monkeypatch, tmp_path):
    panel = {
        "tie": {"a": {"reached": True}, "b": {"reached": False}},
        "two_zero": {"a": {"reached": True}, "b": {"reached": True}},
        "two_one": {
            "a": {"reached": False}, "b": {"reached": False}, "c": {"reached": True}
        },
        "missing": {"a": {"reached": None}},
    }
    (tmp_path / "answer-key.json").write_text(json.dumps({
        key: {"panel": value} for key, value in panel.items()
    }))
    (tmp_path / "scoring-sheet-filled.csv").write_text(
        "packet_id,reached(y/n)\ntie,y\ntwo_zero,y\ntwo_one,n\nmissing,n\n"
    )
    monkeypatch.setattr(ih.layout, "EXP0_HUMAN", tmp_path)
    gate = ih._gate_human([])
    assert gate["status"] == ih.PASS
    assert "n=2" in gate["detail"]
    assert "1 tied" in gate["detail"]
