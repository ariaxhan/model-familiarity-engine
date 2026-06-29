"""Familiarity pilot — pure-logic tests (no network).

Covers the judge's JSON extraction, the empty-output guard (regression for the live
floor gap where empty answers leaked the known outcome), the deterministic spine
checks, and corpus/task wiring.
"""

from __future__ import annotations

import pytest

from model_familiarity.judge import _extract_json, judge
from model_familiarity.tasks import get_task, load_tasks


class _ExplodingProvider:
    """Provider that fails if complete() is ever called — proves the empty-output
    guard short-circuits BEFORE hitting the judge LLM."""

    name = "exploding"

    async def complete(self, *a, **k):
        raise AssertionError("judge called the LLM on empty output — guard failed")

    async def list_models(self):
        return []

    async def is_available(self):
        return True


# --- empty-output guard (the live floor-gap regression) ---


@pytest.mark.parametrize("blank", ["", "   ", "\n\t  \n"])
async def test_empty_output_scores_worse_without_calling_judge(blank):
    task = get_task("ios_zoom")
    v = await judge(task, blank, _ExplodingProvider())
    assert v.reached is False
    assert v.divergence == "worse"
    assert v.parse_ok is True


# --- JSON extraction ---


def test_extract_plain_json():
    assert _extract_json('{"reached": true, "divergence": "better"}')["reached"] is True


def test_extract_fenced_json():
    text = 'Sure:\n```json\n{"reached": false, "divergence": "worse"}\n```'
    assert _extract_json(text)["divergence"] == "worse"


def test_extract_embedded_json():
    text = 'My verdict is {"reached": true, "divergence": "novel"} based on the answer.'
    assert _extract_json(text)["divergence"] == "novel"


def test_extract_garbage_returns_none():
    assert _extract_json("no json here at all") is None


# --- deterministic spines (calibration anchors) ---


def test_spine_ios_zoom_hits_on_16px():
    t = get_task("ios_zoom")
    reached, _ = t.spine("The input font is under 16px which makes iOS zoom on focus.")
    assert reached is True
    reached2, _ = t.spine("It's a flexbox resizing problem, add flex-shrink.")
    assert reached2 is False


def test_spine_cover_crop_hits_on_ratio_mismatch():
    t = get_task("cover_crop")
    reached, _ = t.spine("Card is 3:4 but the strip is 9:16, object-fit cover crops it.")
    assert reached is True


def test_spine_revenuecat_hits_on_whole_period():
    t = get_task("annual_price")
    reached, _ = t.spine("priceString is the whole annual price, divide by 12 for per month.")
    assert reached is True


# --- corpus/task wiring ---


def test_three_sample_tasks_load_with_required_fields():
    tasks = load_tasks()
    assert {t.task_id for t in tasks} == {"ios_zoom", "cover_crop", "annual_price"}
    for t in tasks:
        assert t.prompt and t.known_outcome and t.followup
        assert callable(t.spine)
        assert t.repo_ref.get("kind") == "sample-known-outcome-task"
