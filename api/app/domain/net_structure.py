"""The graph of a net, flattened from the page tree: what inspection reads."""

from __future__ import annotations

from typing import Literal

from .models import DomainModel
from .net_document import Arc, NetDocument, NetKind, RefPlace, RefTransition


class StructureNode(DomainModel):
    """A place or a transition with the name it has in the net."""

    id: str
    name: str | None
    kind: Literal["place", "transition"]
    # Token count of a place in a P/T net (0 when unmarked); undefined for other kinds of net.
    tokens: int | None = None


class StructureArc(DomainModel):
    """An arc whose ends are real nodes: reference nodes are already resolved."""

    id: str
    source: str
    target: str
    # Weight of an arc in a P/T net (1 when there is no inscription); undefined otherwise.
    weight: int | None = None


class NetStructure(DomainModel):
    """Places, transitions and arcs of a net, each list sorted by id."""

    net_id: str
    kind: NetKind
    places: tuple[StructureNode, ...]
    transitions: tuple[StructureNode, ...]
    arcs: tuple[StructureArc, ...]
    has_reference_nodes: bool


def build_structure(*, document: NetDocument, net_id: str) -> NetStructure:
    """Flatten a validated document, resolving reference nodes to the nodes they stand for."""
    is_pt = document.kind == "pt"
    places: list[StructureNode] = []
    transitions: list[StructureNode] = []
    raw_arcs: list[Arc] = []
    reference_to: dict[str, str] = {}
    for located in document.located_containers():
        container = located.container
        for place in container.places:
            marking = place.initial_marking
            tokens = None
            if is_pt:
                tokens = int(marking.text) if marking is not None and marking.text else 0
            name = None if place.name is None else place.name.text
            places.append(StructureNode(id=place.id, name=name, kind="place", tokens=tokens))
        for transition in container.transitions:
            name = None if transition.name is None else transition.name.text
            transitions.append(StructureNode(id=transition.id, name=name, kind="transition"))
        references: tuple[RefPlace | RefTransition, ...] = (
            *container.ref_places,
            *container.ref_transitions,
        )
        for reference in references:
            reference_to[reference.id] = reference.ref
        raw_arcs.extend(container.arcs)

    arcs = []
    for arc in raw_arcs:
        weight = None
        if is_pt:
            inscription = arc.inscription
            weight = int(inscription.text) if inscription is not None and inscription.text else 1
        # Follow reference nodes down to the real place or transition (the document is valid, so
        # chains end).
        ends = []
        for end in (arc.source, arc.target):
            current = end
            while current in reference_to:
                current = reference_to[current]
            ends.append(current)
        arcs.append(StructureArc(id=arc.id, source=ends[0], target=ends[1], weight=weight))
    return NetStructure(
        net_id=net_id,
        kind=document.kind,
        places=tuple(sorted(places, key=lambda node: node.id)),
        transitions=tuple(sorted(transitions, key=lambda node: node.id)),
        arcs=tuple(sorted(arcs, key=lambda arc: arc.id)),
        has_reference_nodes=bool(reference_to),
    )
