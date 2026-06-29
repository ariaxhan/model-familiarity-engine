"""Provider backends for talking to LLM endpoints."""

import os

from model_familiarity.providers.bedrock import BedrockProvider
from model_familiarity.providers.claude_cli import ClaudeCLIProvider
from model_familiarity.providers.openai_compat import OpenAICompatProvider

__all__ = [
    "OpenAICompatProvider",
    "BedrockProvider",
    "ClaudeCLIProvider",
    "get_provider",
]


def get_provider(name: str, **kwargs):
    """Factory for provider instances."""
    providers = {
        "ollama": lambda: OpenAICompatProvider(
            base_url=kwargs.get("base_url", "http://localhost:11434/v1"),
            name="ollama",
        ),
        "bedrock": lambda: BedrockProvider(
            profile=kwargs.get("profile") or os.environ.get("AWS_PROFILE"),
            region=kwargs.get("region") or os.environ.get("AWS_REGION"),
        ),
        "claude-cli": lambda: ClaudeCLIProvider(),
        "openai-compat": lambda: OpenAICompatProvider(
            base_url=kwargs["base_url"],
            api_key=kwargs.get("api_key", ""),
            name=kwargs.get("name", "custom"),
        ),
        "lmstudio": lambda: OpenAICompatProvider(
            base_url=kwargs.get("base_url", "http://localhost:1234/v1"),
            name="lmstudio",
        ),
        # Anthropic via its OpenAI-compatible endpoint. Key from env only —
        # never passed on the CLI or written to disk. Bench raw models at
        # temperature 0 (no Claude Code system prompt / tool wrapper).
        "anthropic": lambda: OpenAICompatProvider(
            base_url=kwargs.get("base_url", "https://api.anthropic.com/v1"),
            api_key=kwargs.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", ""),
            name="anthropic",
        ),
    }
    if name not in providers:
        raise ValueError(f"Unknown provider: {name}. Available: {list(providers.keys())}")
    return providers[name]()
