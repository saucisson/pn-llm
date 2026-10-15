"""The incidence matrix of a P/T net, shared by the invariant analyses."""

from __future__ import annotations

from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure, StructureNode


class Incidence(DomainModel):
    """Rows are places, columns transitions; a cell is tokens produced minus tokens consumed."""

    places: tuple[StructureNode, ...]
    transitions: tuple[StructureNode, ...]
    matrix: tuple[tuple[int, ...], ...]


def incidence_of(*, structure: NetStructure) -> Incidence:
    """Build the incidence matrix; an arc without inscription weighs one."""
    place_index = {place.id: position for position, place in enumerate(structure.places)}
    transition_index = {t.id: position for position, t in enumerate(structure.transitions)}
    matrix = [[0] * len(transition_index) for _ in place_index]
    for arc in structure.arcs:
        weight = arc.weight or 1
        if arc.source in place_index:  # place -> transition: consumed
            matrix[place_index[arc.source]][transition_index[arc.target]] -= weight
        else:  # transition -> place: produced
            matrix[place_index[arc.target]][transition_index[arc.source]] += weight
    return Incidence(
        places=structure.places,
        transitions=structure.transitions,
        matrix=tuple(tuple(row) for row in matrix),
    )
