"""Base provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    latency_ms: float
    tokens_used: int
    model: str
    raw: dict | None = None
    # Optional richer accounting (Bedrock provider records these; others may leave
    # them None). input/output split makes cost-per-task computable; reasoning holds
    # a reasoning model's thinking trace, kept separate from the final answer so the
    # judge never scores the scratchpad.
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    reasoning: str | None = None


class BaseProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        ...
