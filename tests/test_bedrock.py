"""Bedrock provider — pure-logic tests (no network).

Covers the two pieces that must be right regardless of AWS: splitting a Converse
response into answer-vs-reasoning, and cost estimation (known model priced, unknown
model returns None rather than a fabricated number).
"""

from __future__ import annotations

from model_familiarity.providers.bedrock import BedrockProvider, _estimate_cost, _price_for


def test_parse_plain_text():
    resp = {
        "output": {"message": {"content": [{"text": "391"}]}},
        "usage": {"inputTokens": 22, "outputTokens": 2, "totalTokens": 24},
    }
    content, reasoning = BedrockProvider._parse(resp)
    assert content == "391"
    assert reasoning == ""


def test_parse_separates_reasoning_from_answer():
    """Reasoning-model output must NOT bleed into content (judge never sees scratchpad)."""
    resp = {
        "output": {
            "message": {
                "content": [
                    {"reasoningContent": {"reasoningText": {"text": "17*23 = 391, so..."}}},
                    {"text": "391"},
                ]
            }
        }
    }
    content, reasoning = BedrockProvider._parse(resp)
    assert content == "391"
    assert "17*23" in reasoning
    assert "391" not in reasoning.split("=")[0]  # reasoning is the trace, not the bare answer


def test_parse_empty_content():
    content, reasoning = BedrockProvider._parse({"output": {"message": {"content": []}}})
    assert content == ""
    assert reasoning == ""


def test_pricing_known_model():
    assert _price_for("deepseek.v3.2") == (0.62, 1.85)
    assert _price_for("us.meta.llama4-maverick-17b-instruct-v1:0") == (0.24, 0.80)


def test_pricing_unknown_model_is_none():
    assert _price_for("minimax.minimax-m2") is None
    assert _estimate_cost("minimax.minimax-m2", 100, 100) is None


def test_estimate_cost_math():
    # deepseek.v3: 1M in @0.62 + 1M out @1.85 = 2.47
    assert _estimate_cost("deepseek.v3.2", 1_000_000, 1_000_000) == 0.62 + 1.85
    assert _estimate_cost("deepseek.v3.2", 0, 0) == 0.0
