"""What the LLM port exchanges: messages, tool specifications and steps (ADR 0009).

Nothing here depends on a provider. A provider adapter turns these models into its own request
and back; the agent works only with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .models import DomainModel


class LlmToolCall(DomainModel):
    """The model asks for a tool. ``arguments`` is the JSON text the model wrote, unchecked."""

    call_id: str
    tool: str
    arguments: str


class LlmMessage(DomainModel):
    """One message of the conversation as the model sees it.

    ``user`` messages hold what the user said (and quoted untrusted text), ``assistant``
    messages what the model wrote and the tools it asked for, ``tool`` messages the answer to one
    tool call.
    """

    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: tuple[LlmToolCall, ...] = ()
    # For a ``tool`` message: the call it answers, and whether the tool succeeded.
    tool_call_id: str | None = None
    tool_ok: bool = True


class ToolSpec(DomainModel):
    """A tool offered to the model: its name, what it does, and the JSON Schema of its input."""

    name: str
    description: str
    input_schema: str = Field(description="JSON Schema of the arguments, as JSON text")


class LlmStep(DomainModel):
    """The next thing the model does: some text, some tool calls, or both."""

    text: str = ""
    tool_calls: tuple[LlmToolCall, ...] = ()
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
