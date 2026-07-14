"""LHCR replay harness — drive a challenge as a real multi-turn conversation.

For each challenge the model gets the ``initial_prompt`` (turn 0), then each frustrated,
content-free follow-up in order. Crucially the model's OWN prior answers are fed back as
assistant turns, so the conversation is genuine: turn N sees turns 0..N-1. This is what lets
us measure state-holding, no-regression, and layer-switching — none observable in one shot.

Every outgoing user message passes the redaction gate (``assert_clean``) at the send
boundary. The challenges in ``challenges.py`` are authored clean, but this is the fail-closed
guarantee that nothing un-scrubbed ever leaves for a third-party model (I0.9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from model_familiarity.challenges import ConversationSpec
from model_familiarity.providers.base import BaseProvider, SafetyLimitError
from model_familiarity.redact import assert_clean


@dataclass
class Turn:
    index: int
    role: str  # "user" | "assistant"
    text: str
    reasoning_chars: int = 0
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    def to_dict(self) -> dict:
        d = {"index": self.index, "role": self.role, "text": self.text}
        if self.role == "assistant":
            d.update(
                reasoning_chars=self.reasoning_chars,
                latency_ms=round(self.latency_ms, 1) if self.latency_ms else None,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cost_usd=self.cost_usd,
            )
        return d


@dataclass
class Conversation:
    challenge_id: str
    model: str
    turns: list[Turn] = field(default_factory=list)
    error: str | None = None
    # env-driven mode only: did the frustrated-user env accept a correct fix, and on which
    # assistant turn (1-indexed). None = never solved within the turn cap.
    solved: bool = False
    turns_to_fix: int | None = None
    probes_revealed: list[str] = field(default_factory=list)

    @property
    def assistant_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == "assistant"]

    @property
    def final_answer(self) -> str:
        a = self.assistant_turns
        return a[-1].text if a else ""

    @property
    def all_assistant_text(self) -> str:
        """Every model turn concatenated. The root cause may be articulated mid-conversation
        (the last user turn is often a 'now prevent it / clean it up' nudge), so 'reached' is
        assessed cumulatively across the whole conversation, not only on the final turn."""
        return "\n\n".join(t.text for t in self.assistant_turns)

    def transcript(self, max_assistant_chars: int = 4000) -> str:
        """Human/judge-readable transcript with assistant turns capped."""
        lines = []
        for t in self.turns:
            label = "USER" if t.role == "user" else f"MODEL (turn {t.index})"
            body = t.text
            if t.role == "assistant" and len(body) > max_assistant_chars:
                body = body[:max_assistant_chars] + " …[truncated]"
            lines.append(f"[{label}]\n{body}")
        return "\n\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "challenge_id": self.challenge_id,
            "model": self.model,
            "n_assistant_turns": len(self.assistant_turns),
            "error": self.error,
            "solved": self.solved,
            "turns_to_fix": self.turns_to_fix,
            "probes_revealed": self.probes_revealed,
            "turns": [t.to_dict() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        """Rebuild a Conversation from its saved record — used to re-feed an already-run
        transcript to the judge (identical-packet re-score, variance) without re-running the
        (expensive) conversation. Only the fields the judge reads are reconstructed."""
        convo = cls(challenge_id=d["challenge_id"], model=d["model"],
                    error=d.get("error"), solved=bool(d.get("solved", False)),
                    turns_to_fix=d.get("turns_to_fix"),
                    probes_revealed=list(d.get("probes_revealed", [])))
        for t in d.get("turns", []):
            convo.turns.append(Turn(index=t["index"], role=t["role"], text=t.get("text", "")))
        return convo


def _compose_initial(challenge: ConversationSpec) -> str:
    """First user message = the ask plus any code/observation context, as fenced blocks.
    This is how the harder challenges 'show the model the code': real (genericized) source
    and a runtime/observation block, so the bug is found by reading the cascade/seam."""
    if not challenge.code_context:
        return challenge.initial_prompt
    blocks = [challenge.initial_prompt, "\n--- relevant code / observations ---"]
    for name, body in challenge.code_context.items():
        blocks.append(f"\n`{name}`:\n```\n{body}\n```")
    return "\n".join(blocks)


async def run_conversation(
    challenge: ConversationSpec,
    provider: BaseProvider,
    model: str,
    max_tokens: int = 12000,
) -> Conversation:
    """Replay one challenge as a full multi-turn conversation through ``model``.

    Returns the Conversation with every turn recorded. If a provider call fails on a
    given turn, the conversation is returned with what completed so far and ``error`` set
    — one model's failure never aborts the sweep (the runner records and continues).
    """
    convo = Conversation(challenge_id=challenge.challenge_id, model=model)

    # ordered user messages: initial prompt (+ code context), then each follow-up
    user_messages = [_compose_initial(challenge), *challenge.followups]
    history: list[dict] = []  # simple {"role","text"} list fed to provider.converse

    idx = 0
    for um in user_messages:
        assert_clean(um)  # fail-closed: nothing un-redacted leaves
        convo.turns.append(Turn(index=idx, role="user", text=um))
        history.append({"role": "user", "text": um})
        idx += 1

        try:
            resp = await provider.converse(
                model=model,
                system_prompt="",
                messages=history,
                max_tokens=max_tokens,
                temperature=0.0,
            )
        except SafetyLimitError:
            raise
        except Exception as e:  # noqa: BLE001 — record + stop ordinary provider failures
            convo.error = f"{type(e).__name__}: {e}"
            return convo

        answer = resp.content or ""
        convo.turns.append(
            Turn(
                index=idx,
                role="assistant",
                text=answer,
                reasoning_chars=len(resp.reasoning) if resp.reasoning else 0,
                latency_ms=resp.latency_ms,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_usd=resp.cost_usd,
            )
        )
        # feed the model's own answer back as the assistant turn. If the model emitted no
        # text (e.g. a reasoning model that overflowed its budget), send a single space so
        # the Converse API accepts the assistant turn instead of rejecting an empty block.
        history.append({"role": "assistant", "text": answer if answer.strip() else " "})
        idx += 1

    return convo
