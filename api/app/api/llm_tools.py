"""Which routes may be offered to the LLM as tools (ADR 0013, ADR 0015).

Every route is a tool except the ones that return or accept the net itself, which exist for
humans and clients. The tool facade of the chat workflow builds its list with ``offered_to_llm``.
"""

from __future__ import annotations

from app.domain.models import DomainModel


class Operation(DomainModel):
    """An HTTP operation: method and path template as in the OpenAPI document."""

    method: str
    path: str


NET_ITSELF = (
    Operation(method="post", path="/v1/nets"),
    Operation(method="get", path="/v1/nets/{net_id}"),
)


def offered_to_llm(*, operation: Operation) -> bool:
    """Tell whether an operation may be a tool of the LLM."""
    return operation not in NET_ITSELF
