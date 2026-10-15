"""Stored nets: the summary of a document, what the repository returns, and input formats."""

from __future__ import annotations

from enum import StrEnum

from .errors import InvalidNetError
from .models import DomainModel
from .net_document import NetDocument, NetKind


class NetFormat(StrEnum):
    """Serializations of a net accepted on input."""

    JSON = "json"
    PNML = "pnml"


class NetSummary(DomainModel):
    """What the API says about a stored net. Names are reached through inspection, not here."""

    net_id: str
    source_id: str
    kind: NetKind
    parent_id: str | None = None
    reductions_applied: tuple[str, ...] = ()
    pages: int
    places: int
    transitions: int
    arcs: int
    # Only P/T nets have integer markings; for other kinds the total is not defined.
    initial_tokens: int | None = None


class StoredNet(DomainModel):
    """A net as stored: its summary and its canonical document."""

    summary: NetSummary
    document: NetDocument


class SavedNet(DomainModel):
    """Result of storing a net: what is stored and whether this call created it."""

    stored: StoredNet
    created: bool


class NetRegistration(DomainModel):
    """Answer to ``POST /v1/nets``: the id, whether the net is new, and its summary."""

    net_id: str
    created: bool
    summary: NetSummary


def summarize_document(*, document: NetDocument, net_id: str) -> NetSummary:
    """Count the elements of a validated document.

    Raises:
        InvalidNetError: if the net has no place or no transition (engines cannot use it).
    """
    containers = tuple(located.container for located in document.located_containers())
    places = sum(len(container.places) for container in containers)
    transitions = sum(len(container.transitions) for container in containers)
    if places == 0 or transitions == 0:
        message = "Empty net: at least one place and one transition are required"
        raise InvalidNetError(message)
    tokens = None
    if document.kind == "pt":
        tokens = sum(
            int(place.initial_marking.text)
            for container in containers
            for place in container.places
            if place.initial_marking is not None and place.initial_marking.text is not None
        )
    return NetSummary(
        net_id=net_id,
        source_id=document.source_id,
        kind=document.kind,
        pages=len(containers) - 1,
        places=places,
        transitions=transitions,
        arcs=sum(len(container.arcs) for container in containers),
        initial_tokens=tokens,
    )


class NetReferences(DomainModel):
    """What uses a net: jobs and sessions, and how many of them are queued or running."""

    jobs: int
    sessions: int
    live: int
