"""Calls the real Anthropic API once. Skipped unless a key is set; costs a few tokens."""

import os

import pytest

from app.domain.llm import LlmMessage, ToolSpec
from app.infrastructure.anthropic_llm import AnthropicLlm

pytestmark = pytest.mark.live

KEY = os.environ.get("PNVERIF_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


@pytest.mark.skipif(KEY is None, reason="no Anthropic key in the environment")
def test_the_model_calls_a_tool_when_asked_to():
    gateway = AnthropicLlm(
        api_key=KEY or "",
        model=os.environ.get("PNVERIF_ANTHROPIC_MODEL", "claude-opus-4-8"),
        max_tokens=500,
    )
    tools = (
        ToolSpec(
            name="net_summary",
            description="Counts of the net.",
            input_schema='{"type": "object", "properties": {}}',
        ),
    )
    step = gateway.next_step(
        system="You use tools.",
        messages=(LlmMessage(role="user", text="Call net_summary now."),),
        tools=tools,
    )
    assert [call.tool for call in step.tool_calls] == ["net_summary"]
    assert step.input_tokens > 0
