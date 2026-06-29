"""Divergence judge — an LLM call, reference-anchored to the objective outcome.

Given a task's *known-correct outcome* and a model's answer, the judge emits
``{reached, divergence ∈ equivalent|better|worse|novel, how}``. It is told to judge
against the outcome's substance and explicitly NOT to reward resemblance to any
reference assistant — different wording that reaches the outcome is ``equivalent`` or
``better``, never ``worse`` (commission: a clone detector is a failed build).

Two guards make the judge trustworthy rather than trusted:

1. **Anchor = the objective outcome, not Claude's text.** Claude's reference answer is
   never shown to the judge, so it cannot anchor on Claude's phrasing.
2. **Spine cross-check.** The deterministic spine (tasks.py) is computed independently;
   the judge's ``reached`` must agree with it where it exists (commission O3).
   Disagreement is recorded on the verdict (``agrees_with_spine = False``), never hidden.

The judge is floor-tested live before any verdict is trusted (see floor.py): a dummy
answer must score not-reached/``worse``; a differently-worded-correct answer must score
``reached``. A judge that fails either is a failed build.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from model_familiarity.providers.base import BaseProvider
from model_familiarity.tasks import TaskSpec

DEFAULT_JUDGE_MODEL = "qwen.qwen3-235b-a22b-2507-v1:0"

_DIVERGENCES = {"equivalent", "better", "worse", "novel"}

_SYSTEM = (
    "You are an impartial evaluator. You compare a model's answer to a known-correct "
    "OUTCOME for a task and decide whether the answer reached that outcome and how it "
    "diverged. Judge against the substance of the known-correct outcome, never against "
    "writing style or resemblance to any particular assistant. A correct answer phrased "
    "differently still reached the outcome."
)


def _build_prompt(task: TaskSpec, output: str) -> str:
    return f"""TASK:
{task.prompt}

KNOWN-CORRECT OUTCOME (the ground truth to judge against):
{task.known_outcome}

MODEL ANSWER TO EVALUATE:
{output}

Decide:
- reached: true if the model answer reaches the known-correct outcome (substance, not
  wording); false otherwise.
- divergence: exactly one of
  - "equivalent": reached the outcome, materially the same result.
  - "better": reached AND meaningfully superior (caught more, more correct/complete, safer).
  - "worse": failed to reach the outcome, or incomplete/incorrect.
  - "novel": reached a legitimate, correct outcome by a notably different path or a
    different-but-valid answer than expected.
- how: one or two sentences citing specifics from the answer.

Judge ONLY against the known-correct outcome. Do NOT reward similarity to any reference
assistant; different wording that reaches the outcome is "equivalent" or "better",
never "worse".

Respond with ONLY a JSON object, no prose, no code fence:
{{"reached": true_or_false, "divergence": "equivalent|better|worse|novel", "how": "..."}}"""


@dataclass
class Verdict:
    task_id: str
    reached: bool | None
    divergence: str
    how: str
    spine_reached: bool
    spine_detail: str
    agrees_with_spine: bool
    judge_model: str
    parse_ok: bool
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "reached": self.reached,
            "divergence": self.divergence,
            "how": self.how,
            "spine_reached": self.spine_reached,
            "spine_detail": self.spine_detail,
            "agrees_with_spine": self.agrees_with_spine,
            "judge_model": self.judge_model,
            "parse_ok": self.parse_ok,
        }


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a possibly-noisy model reply."""
    # strip code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = brace.group(0) if brace else None
    if candidate is None:
        return None
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


async def judge(
    task: TaskSpec,
    output: str,
    provider: BaseProvider,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    max_tokens: int = 600,
) -> Verdict:
    """Run the LLM judge on *output* for *task*, cross-checked against the spine."""
    spine_reached, spine_detail = task.spine(output)

    # Empty / blank output never reaches the outcome. Short-circuit deterministically
    # BEFORE calling the judge — otherwise the judge can leak the known-correct outcome
    # from its own prompt and rubber-stamp "reached" onto nothing (floor gap found live:
    # a reasoning model that spent its whole budget thinking emitted empty content).
    if not output or not output.strip():
        return Verdict(
            task_id=task.task_id,
            reached=False,
            divergence="worse",
            how="model produced no answer text (empty output)",
            spine_reached=spine_reached,
            spine_detail=spine_detail,
            agrees_with_spine=(spine_reached is False),
            judge_model=judge_model,
            parse_ok=True,
            raw_text="",
        )

    resp = await provider.complete(
        model=judge_model,
        system_prompt=_SYSTEM,
        user_prompt=_build_prompt(task, output),
        max_tokens=max_tokens,
        temperature=0.0,
    )
    obj = _extract_json(resp.content)

    if obj is None or "reached" not in obj or "divergence" not in obj:
        return Verdict(
            task_id=task.task_id,
            reached=None,
            divergence="parse_error",
            how=resp.content[:200],
            spine_reached=spine_reached,
            spine_detail=spine_detail,
            agrees_with_spine=False,
            judge_model=judge_model,
            parse_ok=False,
            raw_text=resp.content,
        )

    reached = bool(obj["reached"])
    divergence = str(obj["divergence"]).strip().lower()
    if divergence not in _DIVERGENCES:
        divergence = "parse_error"
    how = str(obj.get("how", "")).strip()

    return Verdict(
        task_id=task.task_id,
        reached=reached,
        divergence=divergence,
        how=how,
        spine_reached=spine_reached,
        spine_detail=spine_detail,
        agrees_with_spine=(reached == spine_reached),
        judge_model=judge_model,
        parse_ok=True,
        raw_text=resp.content,
    )
