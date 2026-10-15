"""Analysis ``p-invariants``: minimal-support place invariants of a P/T net."""

from __future__ import annotations

from pydantic import Field

from app.domain.contract import ElementRef
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure

from .semiflows import minimal_semiflows


class PInvariantsParameters(DomainModel):
    """Options of the search."""

    # Stop the search when the working set grows beyond this many rows (the result then says so).
    max_rows: int = Field(default=20_000, ge=1, le=1_000_000)
    # At most this many invariants are listed; the total is always given.
    max_invariants: int = Field(default=200, ge=1, le=10_000)


class WeightedElement(DomainModel):
    """An element of an invariant and its weight."""

    element: ElementRef
    weight: int = Field(ge=1)


class PInvariant(DomainModel):
    """A place invariant: the weighted sum of the tokens of its places never changes."""

    elements: tuple[WeightedElement, ...]
    # The value of that sum, from the initial marking.
    constant: int = Field(ge=0)


class PInvariantsResult(DomainModel):
    """The minimal-support invariants found, and how far the search went."""

    invariants: tuple[PInvariant, ...]
    total: int
    # False when the search stopped at its bound: there may be more invariants than listed.
    complete: bool
    # Places in no invariant are not structurally bounded by this analysis alone.
    uncovered_places: tuple[ElementRef, ...]


def p_invariants(
    *, structure: NetStructure, parameters: PInvariantsParameters
) -> PInvariantsResult:
    """Compute the minimal-support P-invariants of a P/T net from its incidence matrix."""
    places = structure.places
    index = {place.id: position for position, place in enumerate(places)}
    transitions = {t.id: position for position, t in enumerate(structure.transitions)}
    matrix = [[0] * len(transitions) for _ in places]
    for arc in structure.arcs:
        weight = arc.weight or 1
        if arc.source in index:  # place -> transition consumes
            matrix[index[arc.source]][transitions[arc.target]] -= weight
        else:  # transition -> place produces
            matrix[index[arc.target]][transitions[arc.source]] += weight
    found = minimal_semiflows(matrix=matrix, max_rows=parameters.max_rows)
    invariants = tuple(
        PInvariant(
            elements=tuple(
                WeightedElement(element=ref_of(node=places[position]), weight=weight)
                for position, weight in enumerate(flow)
                if weight
            ),
            constant=sum(
                weight * (places[position].tokens or 0) for position, weight in enumerate(flow)
            ),
        )
        for flow in found.flows
    )
    covered = {w.element.id for invariant in invariants for w in invariant.elements}
    return PInvariantsResult(
        invariants=invariants[: parameters.max_invariants],
        total=len(invariants),
        complete=found.complete,
        uncovered_places=tuple(ref_of(node=p) for p in places if p.id not in covered),
    )
