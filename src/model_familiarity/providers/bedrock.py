"""AWS Bedrock provider using the Converse API."""

from __future__ import annotations

import asyncio
import os
import time

from model_familiarity.providers.base import BaseProvider, LLMResponse

# Per-1M-token (input, output) USD pricing, matched by id substring. Best-effort:
# used only to annotate cost. Unknown models record token split with cost_usd=None
# rather than a fabricated number.
_PRICING: dict[str, tuple[float, float]] = {
    "deepseek.v3": (0.62, 1.85),
    "deepseek.r1": (1.35, 5.40),
    "llama4-maverick": (0.24, 0.80),
    "llama4-scout": (0.17, 0.66),
}


def _price_for(model_id: str) -> tuple[float, float] | None:
    for key, price in _PRICING.items():
        if key in model_id:
            return price
    return None


def _estimate_cost(model_id: str, in_tok: int, out_tok: int) -> float | None:
    price = _price_for(model_id)
    if price is None:
        return None
    in_per_m, out_per_m = price
    return (in_tok / 1_000_000) * in_per_m + (out_tok / 1_000_000) * out_per_m


class BedrockProvider(BaseProvider):
    name = "bedrock"

    def __init__(self, profile: str | None = None, region: str | None = None):
        self.profile = profile
        self.region = region or os.environ.get("AWS_REGION", "us-west-2")
        self._runtime = None
        self._control = None

    # --- lazy clients (so import / construction never needs AWS) ---
    def _runtime_client(self):
        if self._runtime is None:
            import boto3
            from botocore.config import Config

            # Reasoning models (R1, Kimi, MiniMax) can think for minutes at a large token
            # budget; the boto default 60s read timeout kills them mid-thought. 300s + a
            # few adaptive retries keeps the sweep alive across slow models.
            cfg = Config(
                read_timeout=300,
                connect_timeout=15,
                retries={"max_attempts": 3, "mode": "adaptive"},
            )
            session = boto3.Session(profile_name=self.profile) if self.profile else boto3.Session()
            self._runtime = session.client("bedrock-runtime", region_name=self.region, config=cfg)
        return self._runtime

    def _control_client(self):
        if self._control is None:
            import boto3

            session = boto3.Session(profile_name=self.profile) if self.profile else boto3.Session()
            self._control = session.client("bedrock", region_name=self.region)
        return self._control

    # --- sync Converse, retried for throttling + temperature rejection ---
    def _converse_sync(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict:
        import re

        from botocore.exceptions import ClientError

        client = self._runtime_client()
        messages = [{"role": "user", "content": [{"text": user_prompt}]}]
        # Mutable so a per-model cap discovered mid-call (8192 on Llama 4, etc.) sticks
        # for the retry instead of re-tripping the same ValidationException.
        cap = max_tokens

        def call(include_temp: bool) -> dict:
            kwargs: dict = {
                "modelId": model,
                "messages": messages,
                "inferenceConfig": {"maxTokens": cap},
            }
            if include_temp:
                kwargs["inferenceConfig"]["temperature"] = temperature
            if system_prompt:
                kwargs["system"] = [{"text": system_prompt}]
            return client.converse(**kwargs)

        backoff = 1.0
        for attempt in range(5):
            try:
                return call(include_temp=True)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                msg = e.response.get("Error", {}).get("Message", "")
                if code in ("ThrottlingException", "TooManyRequestsException"):
                    if attempt == 4:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                if code == "ValidationException" and "temperature" in msg.lower():
                    return call(include_temp=False)
                # Model caps maxTokens below our request -> clamp to its limit and retry
                # once. Keeps 8192-capped models (Llama 4) in the sweep instead of erroring.
                if code == "ValidationException" and "maximum tokens" in msg.lower():
                    m = re.search(r"model limit of (\d+)", msg)
                    if m and int(m.group(1)) < cap:
                        cap = int(m.group(1))
                        return call(include_temp=True)
                raise
        raise RuntimeError("unreachable")

    @staticmethod
    def _parse(resp: dict) -> tuple[str, str]:
        """Split a Converse response into (answer_text, reasoning_text)."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        blocks = resp.get("output", {}).get("message", {}).get("content", []) or []
        for b in blocks:
            if "text" in b:
                text_parts.append(b["text"])
            elif "reasoningContent" in b:
                rt = b["reasoningContent"].get("reasoningText", {})
                if rt.get("text"):
                    reasoning_parts.append(rt["text"])
        return "\n".join(text_parts).strip(), "\n".join(reasoning_parts).strip()

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        t0 = time.perf_counter()
        resp = await asyncio.to_thread(
            self._converse_sync, model, system_prompt, user_prompt, max_tokens, temperature
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        content, reasoning = self._parse(resp)
        usage = resp.get("usage", {}) or {}
        in_tok = int(usage.get("inputTokens", 0))
        out_tok = int(usage.get("outputTokens", 0))
        total = int(usage.get("totalTokens", in_tok + out_tok))

        return LLMResponse(
            content=content,
            latency_ms=latency_ms,
            tokens_used=total,
            model=model,
            raw=resp,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=_estimate_cost(model, in_tok, out_tok),
            reasoning=reasoning or None,
        )

    async def list_models(self) -> list[str]:
        """ACTIVE inference-profile ids (a stable invocable subset of the catalog)."""

        def _list() -> list[str]:
            client = self._control_client()
            out: list[str] = []
            paginator = client.get_paginator("list_inference_profiles")
            for page in paginator.paginate():
                for p in page.get("inferenceProfileSummaries", []):
                    if p.get("status") == "ACTIVE":
                        out.append(p["inferenceProfileId"])
            return out

        return await asyncio.to_thread(_list)

    async def is_available(self) -> bool:
        def _check() -> bool:
            try:
                self._control_client().list_inference_profiles(maxResults=1)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_check)
