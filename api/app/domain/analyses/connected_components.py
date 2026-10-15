"""Analysis ``connected-components``: the parts of a net that are not linked by any arc."""

from __future__ import annotations

from pydantic import Field

from app.domain.contract import ElementRef
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure

from .graph import adjacency


class ConnectedComponentsParameters(DomainModel):
    """Options of the analysis."""

    # At most this many components are listed, the largest first; the total is always given.
    max_components: int = Field(default=50, ge=1, le=10_000)
    # At most this many elements of a component are listed; its size is always given.
    max_elements: int = Field(default=100, ge=1, le=100_000)


class Component(DomainModel):
    """A weakly connected component."""

    places: int
    transitions: int
    elements: tuple[ElementRef, ...]
    truncated: bool


class ConnectedComponentsResult(DomainModel):
    """The components, largest first."""

    components: tuple[Component, ...]
    total: int


def connected_components(
    *, structure: NetStructure, parameters: ConnectedComponentsParameters
) -> ConnectedComponentsResult:
    """Group the elements of a net by weak connectivity (arcs followed in either direction)."""
    graph = adjacency(structure=structure)
    nodes = {n.id: n for n in (*structure.places, *structure.transitions)}
    seen: set[str] = set()
    components = []
    for start in nodes:
        if start in seen:
            continue
        members = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            for following in (*graph.forward.get(current, ()), *graph.backward.get(current, ())):
                if following not in members:
                    members.add(following)
                    pending.append(following)
        seen |= members
        ordered = sorted(members)
        components.append(
            Component(
                places=sum(nodes[m].kind == "place" for m in members),
                transitions=sum(nodes[m].kind == "transition" for m in members),
                elements=tuple(ref_of(node=nodes[m]) for m in ordered[: parameters.max_elements]),
                truncated=len(ordered) > parameters.max_elements,
            )
        )
    components.sort(key=lambda c: (-(c.places + c.transitions), c.elements[0].id))
    return ConnectedComponentsResult(
        components=tuple(components[: parameters.max_components]), total=len(components)
    )
