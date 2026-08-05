"""OpenAI-compatible provider — works with Ollama, LM Studio, vLLM, etc."""

from __future__ import annotations

import time

import httpx

from model_familiarity.providers.base import BaseProvider, LLMResponse

_HARMONY_FINAL = "<|channel|>final<|message|>"


def _extract_final_answer(content: str) -> str:
    """Unwrap raw gpt-oss harmony channel markup if the server didn't.

    Some servers (e.g. mlx_lm.server) return the raw harmony token stream as
    content: analysis-channel reasoning first, then the final channel. If there
    is no final channel, the model never finished answering — return empty.
    Content without channel markup passes through untouched.
    """
    if _HARMONY_FINAL in content:
        final = content.rsplit(_HARMONY_FINAL, 1)[1]
        for stop in ("<|end|>", "<|return|>", "<|start|>"):
            final = final.split(stop, 1)[0]
        return final.strip()
    if "<|channel|>" in content:
        return ""
    return content


class OpenAICompatProvider(BaseProvider):
    def __init__(self, base_url: str, api_key: str = "", name: str = "openai-compat"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = name

    def _headers(self) -> dict[str, str]:
        """Auth headers, or none for keyless local servers (ollama, LM Studio)."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        messages = [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": user_prompt},
        ]
        return await self.converse(model, system_prompt, messages, max_tokens, temperature)

    async def converse(
        self,
        model: str,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        headers = self._headers()

        payload = {
            "model": model,
            "messages": ([{"role": "system", "content": system_prompt}]
                         if system_prompt else [])
            + [{"role": item["role"], "content": item.get("text", item.get("content", ""))}
               for item in messages if item["role"] != "system"],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=300) as client:
            url = f"{self.base_url}/chat/completions"
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        elapsed_ms = (time.perf_counter() - start) * 1000
        data = resp.json()
        # Ported from llm-bench (2026-07-17): reasoning models can exhaust
        # max_tokens inside the reasoning channel (server omits "content"), and
        # some servers (mlx_lm.server) return gpt-oss's raw harmony stream as
        # content. Missing/null content is an empty answer; harmony markup is
        # unwrapped to the final channel.
        content = data["choices"][0]["message"].get("content") or ""
        content = _extract_final_answer(content)
        tokens = data.get("usage", {}).get("total_tokens", 0)

        return LLMResponse(
            content=content,
            latency_ms=elapsed_ms,
            tokens_used=tokens,
            model=model,
            raw=data,
        )

    async def list_models(self) -> list[str]:
        # Hosted providers (Together, Groq, Anthropic) 401 on an unauthenticated
        # /models. Without the header this silently returned [] for every one of them,
        # which reads as "provider has no models" rather than "you forgot the key".
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                return [m["id"] for m in data.get("data", data.get("models", []))]
        except Exception:
            return []

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False
