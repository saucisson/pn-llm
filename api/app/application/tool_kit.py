"""What every tool of the facade is made of: its context, its outcome, and how it answers.

Shared by the tool families (inspection and checks in ``tools``, analyses in ``analysis_tools``)
so that no family imports another.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel, JsonValue, TypeAdapter

from app.domain.contract import Page
from app.domain.descriptions import Description
from app.domain.llm import ToolSpec
from app.domain.models import DomainModel
from app.domain.sessions import Session, SessionEvent


class ToolContext(DomainModel):
    """What a tool may know of the conversation that calls it."""

    session: Session
    description: Description | None = None
    # Set by the facade for each call: the id of the call being served.
    call_id: str = ""


class ToolOutcome(DomainModel):
    """The result of one tool call: the text for the model, and the events it caused."""

    ok: bool
    content: str
    events: tuple[SessionEvent, ...] = ()


class ToolPayload(DomainModel):
    """The trimmed shape of every tool answer (ADR 0017): no envelope noise."""

    status: str
    data: JsonValue = None
    truncated: Page | None = None
    error: str | None = None


class Tool(DomainModel, arbitrary_types_allowed=True):
    """A tool: its specification, the model of its arguments and the function that runs it."""

    spec: ToolSpec
    arguments: type[BaseModel]
    run: Callable[..., ToolOutcome]


def define_tool(
    *, name: str, description: str, arguments: type[BaseModel], run: Callable[..., ToolOutcome]
) -> Tool:
    """Build a tool; the input schema shown to the model comes from the arguments model."""
    schema = json.dumps(arguments.model_json_schema(), sort_keys=True)
    return Tool(
        spec=ToolSpec(name=name, description=description, input_schema=schema),
        arguments=arguments,
        run=run,
    )


def to_json(*, value: object) -> JsonValue:
    """Turn a pydantic value, or a tuple of them, into plain JSON data."""
    adapter: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
    return adapter.validate_python(
        TypeAdapter(type(value)).dump_python(value, mode="json", exclude_none=True)
    )


def failure(*, message: str) -> ToolOutcome:
    """Build the outcome of a tool that could not do what was asked."""
    payload = ToolPayload(status="error", error=message)
    return ToolOutcome(ok=False, content=payload.model_dump_json(exclude_none=True))


def answer(*, data: object, page: Page | None = None) -> ToolOutcome:
    """Build a successful outcome from a result and, for lists, the page information."""
    truncated = page if page is not None and page.next_cursor is not None else None
    payload = ToolPayload(status="ok", data=to_json(value=data), truncated=truncated)
    return ToolOutcome(ok=True, content=payload.model_dump_json(exclude_none=True))
