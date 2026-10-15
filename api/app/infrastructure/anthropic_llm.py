"""The Anthropic Messages API behind the LLM port (ADR 0009).

The only module that imports the provider SDK. It turns the conversation of the agent into a
Messages request (tool results go back in the user turn that follows the assistant turn, as the API
requires) and the answer into a step. Thinking is switched off so that the history the agent
rebuilds from its events stays valid for the provider; a model that binds thinking blocks to its
conversation needs the provider's reasoning state kept with the events, which is future work.
"""

from __future__ import annotations

import json

import anthropic
from anthropic.types import (
    CacheControlEphemeralParam,
    MessageParam,
    TextBlockParam,
    ThinkingConfigDisabledParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)

from app.domain.errors import LlmUnavailableError
from app.domain.llm import LlmMessage, LlmStep, LlmToolCall, ToolSpec

CACHE = CacheControlEphemeralParam(type="ephemeral")


def to_anthropic_messages(*, messages: tuple[LlmMessage, ...]) -> list[MessageParam]:
    """Convert the conversation to the Messages API shape.

    Consecutive tool results share one user turn, and a user message that follows them joins that
    turn after the results, because the API wants every result right after the assistant turn that
    called the tools.
    """
    converted: list[MessageParam] = []
    pending_user: list[TextBlockParam | ToolResultBlockParam] = []
    for message in messages:
        if message.role == "tool":
            pending_user.append(
                ToolResultBlockParam(
                    type="tool_result",
                    tool_use_id=message.tool_call_id or "",
                    content=message.text,
                    is_error=not message.tool_ok,
                )
            )
        elif message.role == "user":
            pending_user.append(TextBlockParam(type="text", text=message.text))
        else:
            if pending_user:
                converted.append(MessageParam(role="user", content=pending_user))
                pending_user = []
            blocks: list[TextBlockParam | ToolUseBlockParam] = []
            if message.text:
                blocks.append(TextBlockParam(type="text", text=message.text))
            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                except ValueError:
                    arguments = {}
                blocks.append(
                    ToolUseBlockParam(
                        type="tool_use", id=call.call_id, name=call.tool, input=arguments
                    )
                )
            if blocks:
                converted.append(MessageParam(role="assistant", content=blocks))
    if pending_user:
        converted.append(MessageParam(role="user", content=pending_user))
    return converted


def to_anthropic_tools(*, tools: tuple[ToolSpec, ...]) -> list[ToolParam]:
    """Convert the tool specifications; the last one carries the cache breakpoint."""
    converted: list[ToolParam] = []
    for index, tool in enumerate(tools):
        schema = json.loads(tool.input_schema)
        if index == len(tools) - 1:
            converted.append(
                ToolParam(
                    name=tool.name,
                    description=tool.description,
                    input_schema=schema,
                    cache_control=CACHE,
                )
            )
        else:
            converted.append(
                ToolParam(name=tool.name, description=tool.description, input_schema=schema)
            )
    return converted


class AnthropicLlm:
    """An LLM gateway over the Anthropic Messages API."""

    def __init__(self, *, api_key: str, model: str, max_tokens: int) -> None:
        """Create the client; the key is held by the SDK client only."""
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def next_step(
        self, *, system: str, messages: tuple[LlmMessage, ...], tools: tuple[ToolSpec, ...]
    ) -> LlmStep:
        """Ask the model for its next step.

        Raises:
            LlmUnavailableError: if the key is refused, the API cannot be reached, or the model
                declined the request.
        """
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[TextBlockParam(type="text", text=system, cache_control=CACHE)],
                messages=to_anthropic_messages(messages=messages),
                tools=to_anthropic_tools(tools=tools),
                thinking=ThinkingConfigDisabledParam(type="disabled"),
            )
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.APIConnectionError,
        ) as exc:
            raise LlmUnavailableError(
                f"The language model cannot be used: {type(exc).__name__}"
            ) from exc
        if response.stop_reason == "refusal":
            raise LlmUnavailableError("The language model declined this request")
        texts = [block.text for block in response.content if block.type == "text"]
        calls = tuple(
            LlmToolCall(call_id=block.id, tool=block.name, arguments=json.dumps(block.input))
            for block in response.content
            if block.type == "tool_use"
        )
        return LlmStep(
            text="\n".join(texts),
            tool_calls=calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
