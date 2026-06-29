"""Claude Code headless provider — runs models via the local `claude -p` CLI.

Uses the existing Claude Code subscription auth (no API key). `--system-prompt`
*replaces* Claude Code's default coding-agent framing, so each call is close to
a raw model completion. Tools are disabled and turns capped at 1 for a clean
single-shot answer.

Caveat for benchmarking: prompts still pass through Claude Code's harness, so
absolute scores are NOT comparable to clean-API providers (ollama, anthropic).
A/B comparisons *within* this provider (e.g. opus-4-8 vs opus-4-7) stay fair —
the harness is a shared constant. The CLI also does not expose temperature or
max_tokens, so those args are accepted but ignored.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

from model_familiarity.providers.base import BaseProvider, LLMResponse


def _extract_result_json(text: str) -> dict | None:
    """Pull the result object out of `claude --output-format json` stdout.

    Session hooks can print trailing noise after the JSON, so a plain
    json.loads of the whole stream may fail. The result is a single-line
    object, so scan lines first, then fall back to a greedy match.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and '"result"' in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    m = re.search(r'\{.*"result".*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


class ClaudeCLIProvider(BaseProvider):
    name = "claude-cli"

    # Headless Claude occasionally returns a transient error (rate limit, 529,
    # empty result) when calls fire back-to-back. The runner scores any
    # exception as 0.0, which would unfairly tank a benchmark, so retry.
    MAX_ATTEMPTS = 3
    RETRY_BACKOFF_S = 4.0

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        last_err: Exception | None = None
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                return await self._complete_once(model, system_prompt, user_prompt)
            except Exception as e:  # noqa: BLE001 — retry any transient failure
                last_err = e
                if attempt < self.MAX_ATTEMPTS - 1:
                    await asyncio.sleep(self.RETRY_BACKOFF_S * (attempt + 1))
        raise RuntimeError(
            f"claude-cli failed after {self.MAX_ATTEMPTS} attempts: {last_err}"
        )

    async def _complete_once(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResponse:
        cmd = [
            "claude",
            "-p",
            user_prompt,
            "--model",
            model,
            "--output-format",
            "json",
            "--allowedTools",
            "",
            "--max-turns",
            "1",
        ]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]

        start = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        elapsed_ms = (time.perf_counter() - start) * 1000

        data = _extract_result_json(stdout.decode())
        if data is None:
            raise RuntimeError(
                f"claude-cli: no JSON result (exit {proc.returncode}). "
                f"stderr={stderr.decode().strip()[:300]} "
                f"stdout={stdout.decode().strip()[:300]}"
            )
        if data.get("is_error"):
            raise RuntimeError(f"claude-cli error: {data.get('result')!r}")

        content = data.get("result", "") or ""
        usage = data.get("usage", {}) or {}
        tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)

        return LLMResponse(
            content=content.strip(),
            latency_ms=elapsed_ms,
            tokens_used=tokens,
            model=model,
            raw=data,
        )

    async def list_models(self) -> list[str]:
        # The CLI has no stable machine-readable model list; return the known
        # headless-reachable ids.
        return [
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ]

    async def is_available(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except Exception:
            return False
