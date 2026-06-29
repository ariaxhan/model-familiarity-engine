"""Replay harness — re-run a mined task through a model, two conditions.

For each task the harness runs:

- ``cold``   : the prompt alone (tests how little hand-holding the model needs).
- ``guided`` : the prompt plus a realistic frustrated follow-up (tasks.py ``followup``).
  The follow-up carries no observational clue and no root cause. This tests whether a
  model makes progress from a bare annoyed nudge, not a structured hint. The gap between
  cold and guided is itself a model trait.

The redaction gate is enforced at the send boundary: ``assert_clean`` runs on the exact
outgoing prompt before any third-party model call. Even though tasks are pre-redacted,
this is the hard fail-closed guarantee that nothing un-scrubbed leaves.
"""

from __future__ import annotations

from dataclasses import dataclass

from model_familiarity.providers.base import BaseProvider
from model_familiarity.redact import assert_clean
from model_familiarity.tasks import TaskSpec

CONDITIONS = ("cold", "guided")


@dataclass
class Replay:
    task_id: str
    model: str
    condition: str
    output: str
    reasoning: str | None
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "condition": self.condition,
            "output": self.output,
            "reasoning_chars": len(self.reasoning) if self.reasoning else 0,
            "latency_ms": round(self.latency_ms, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


def _build_user_prompt(task: TaskSpec, condition: str) -> str:
    if condition == "cold":
        return task.prompt
    if condition == "guided":
        # a realistic frustrated follow-up framed as a second user turn
        return f"{task.prompt}\n\n(follow-up message from the user) {task.followup}"
    raise ValueError(f"unknown condition: {condition}")


async def replay_task(
    task: TaskSpec,
    provider: BaseProvider,
    model: str,
    condition: str,
    max_tokens: int = 2048,
) -> Replay:
    user_prompt = _build_user_prompt(task, condition)
    # Hard gate: nothing un-redacted leaves for the provider.
    assert_clean(user_prompt)

    resp = await provider.complete(
        model=model,
        system_prompt="",
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return Replay(
        task_id=task.task_id,
        model=model,
        condition=condition,
        output=resp.content,
        reasoning=resp.reasoning,
        latency_ms=resp.latency_ms,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cost_usd=resp.cost_usd,
    )
