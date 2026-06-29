"""Curated replay tasks for the public sample pilot.

The bundled tasks are synthetic, known-outcome debugging tasks. They are small enough
to replay without rebuilding a repo and concrete enough for the judge to anchor on a
definite outcome. Replace ``data/sample_tasks.json`` with your own redacted task
corpus before drawing real model-familiarity conclusions. The samples span three
debugging domains:

- ``ios_zoom``            — mobile-web debugging: iOS WKWebView auto-zoom on <16px inputs
- ``cover_crop``          — CSS layout: aspect-ratio mismatch + object-fit cover
- ``annual_price``        — payments logic: whole-period price used as per-month value

For each, this module pairs the reconstructed+redacted prompt/reference (from
``data/sample_tasks.json``) with three things authored from ground truth, not guessed:

- ``known_outcome`` — the objective answer the judge anchors to (NOT Claude's wording).
- ``followup``      — a realistic second message: frustrated, short, and content-free.
  It
  carries NO observational clue, no root cause, no symptom detail — just the annoyed "still
  broken" nudge. The guided condition replays it, testing whether a model can make progress
  from pure frustration with zero new information (only its own prior turn to build on),
  not from a structured hint.
- ``spine``         — a cheap deterministic check (D10). It does NOT judge; it
  *calibrates* the LLM judge: where the spine has a verdict, the judge must agree
  (commission O3), and disagreement is surfaced.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "data" / "sample_tasks.json"


@dataclass
class TaskSpec:
    task_id: str
    capability: str
    prompt: str
    known_outcome: str
    followup: str
    claude_reference: str
    repo_ref: dict
    spine: Callable[[str], tuple[bool, str]]


# --- deterministic spine checks (calibration anchors, not the judge) ---


def _spine_ios_zoom(out: str) -> tuple[bool, str]:
    o = out.lower()
    mentions_16 = "16px" in o or "16 px" in o or "16-pixel" in o or "16 pixel" in o
    reached = mentions_16 and ("zoom" in o) and ("font" in o or "input" in o)
    return reached, "16px-font iOS-zoom identified" if reached else "root cause not identified"


def _spine_cover_crop(out: str) -> tuple[bool, str]:
    o = out.lower()
    ratios = ("3:4" in o or "3/4" in o or "3 / 4" in o) and (
        "9:16" in o or "9/16" in o or "9 / 16" in o
    )
    aspect_words = "aspect" in o and ("ratio" in o or "mismatch" in o)
    reached = (
        (aspect_words and ("object-fit" in o or "cover" in o))
        or ratios
        or ("object-fit" in o and "cover" in o and ("crop" in o or "cut" in o))
    )
    return reached, "aspect-ratio mismatch identified" if reached else "root cause not identified"


def _spine_annual_price(out: str) -> tuple[bool, str]:
    o = out.lower()
    reached = (
        ("pricestring" in o or "price string" in o or "pricestring" in o)
        and (
            "per-period" in o
            or "per period" in o
            or "whole" in o
            or "annual" in o
            or "yearly" in o
            or "/12" in o
            or "divide" in o
            or "per month" in o
            or "per-month" in o
        )
    ) or ("/ 12" in o or "/12" in o) and "month" in o
    detail = "whole-period-as-per-month identified" if reached else "root cause not identified"
    return reached, detail


_SPINES: dict[str, Callable[[str], tuple[bool, str]]] = {
    "ios_zoom": _spine_ios_zoom,
    "cover_crop": _spine_cover_crop,
    "annual_price": _spine_annual_price,
}

_META = {
    "ios_zoom": {
        "capability": "mobile-web debugging (iOS WKWebView)",
        "known_outcome": (
            "iOS Safari/WKWebView auto-zooms the page when a focused input has a computed "
            "font-size under 16px. The .desk-input inherits ~13px, so focusing it triggers "
            "the zoom; with no maximum-scale in the viewport the user can't pinch back. The "
            "correct fix is to set the input font-size to >=16px. The viewport-lock fix "
            "(maximum-scale=1 / user-scalable=no) is inferior — it kills pinch-zoom app-wide "
            "and harms accessibility."
        ),
        "followup": "its still not working. just fix it pls",
    },
    "cover_crop": {
        "capability": "CSS layout / aspect-ratio debugging",
        "known_outcome": (
            "Aspect-ratio mismatch: the cover card is 3:4 but the strip image is 9:16. With "
            "object-fit: cover the taller 9:16 image is scaled to fill the 3:4 box, cropping "
            "the excess height off the top and bottom. The fix is to make the cover card's "
            "aspect-ratio match the strip's 9:16 so the whole image shows."
        ),
        "followup": "still broken, the cover still looks wrong. why. just fix it",
    },
    "annual_price": {
        "capability": "payments-logic / API-semantics debugging",
        "known_outcome": (
            "pkg.product.priceString is the whole-period price (for the annual package, "
            "$79.99/year), not a per-month value — the trailing comment is wrong. Assigning "
            "it to pricePerMonth makes the annual plan render '$79.99/mo'. The fix is to "
            "compute per-month from the annual price (price / 12, same currency) rather than "
            "reusing priceString — $79.99/yr -> $6.67/mo."
        ),
        "followup": "it still shows the wrong price. fix it please",
    },
}


def load_tasks() -> list[TaskSpec]:
    corpus = json.loads(_CORPUS_PATH.read_text())
    tasks: list[TaskSpec] = []
    for tid, meta in _META.items():
        c = corpus[tid]
        tasks.append(
            TaskSpec(
                task_id=tid,
                capability=meta["capability"],
                prompt=c["prompt"],
                known_outcome=meta["known_outcome"],
                followup=meta["followup"],
                claude_reference=c["claude_reference"],
                repo_ref=c.get("repo_ref", {}),
                spine=_SPINES[tid],
            )
        )
    return tasks


def get_task(task_id: str) -> TaskSpec:
    for t in load_tasks():
        if t.task_id == task_id:
            return t
    raise KeyError(task_id)
