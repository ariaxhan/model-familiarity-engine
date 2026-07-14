"""Pure panel configuration and agreement math used by offline study planning."""

from __future__ import annotations

from dataclasses import dataclass

EXP0_ENV_MODEL = "qwen.qwen3-235b-a22b-2507-v1:0"


@dataclass(frozen=True)
class JudgeSpec:
    key: str
    model: str
    family: str
    provider_key: str


DEFAULT_PANEL = [
    JudgeSpec("judge_a", "us.meta.llama3-3-70b-instruct-v1:0", "open", "bedrock"),
    JudgeSpec("judge_b", "us.anthropic.claude-sonnet-4-6", "anthropic", "bedrock"),
    JudgeSpec("judge_c", "gpt-5.1", "openai", "openai"),
]

EXP0_SUBJECTS = [
    "us.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "gpt-5",
    "gpt-5-mini",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "us.deepseek.r1-v1:0",
    "moonshot.kimi-k2-thinking",
    "qwen.qwen3-coder-30b-a3b-v1:0",
    "zai.glm-4.7",
    "us.amazon.nova-2-lite-v1:0",
    "nvidia.nemotron-nano-9b-v2",
]


def provider_family(model: str) -> str:
    if model.startswith(("gpt-", "o3", "o4")):
        return "openai"
    if model.startswith("gemini-"):
        return "gemini"
    if "anthropic" in model or "claude" in model:
        return "anthropic"
    return "open"


def assert_distinct(env_model: str, panel: list[JudgeSpec], subjects: list[str]) -> None:
    judges = {judge.model for judge in panel}
    if len(judges) != len(panel):
        raise ValueError(f"panel has duplicate judge models: {[judge.model for judge in panel]}")
    if env_model in judges:
        raise ValueError(f"env model {env_model!r} is also a judge, env must be held out")
    subject_set = set(subjects)
    overlap = judges & subject_set
    if overlap:
        raise ValueError(
            f"judge model(s) {sorted(overlap)} are also subjects, a model cannot grade itself"
        )
    if env_model in subject_set:
        raise ValueError(f"env model {env_model!r} is also a subject, env must be held out")


def pair_agreement(values: list[object | None]) -> float | None:
    """Fraction of valid judge pairs that agree; undefined below two valid opinions."""
    valid = [value for value in values if value is not None]
    if len(valid) < 2:
        return None
    pairs = [(valid[i], valid[j]) for i in range(len(valid)) for j in range(i + 1, len(valid))]
    return sum(left == right for left, right in pairs) / len(pairs)


def majority(values: list[bool | None]) -> bool | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    true_count = sum(valid)
    if true_count == len(valid) / 2:
        return None
    return true_count > len(valid) / 2
