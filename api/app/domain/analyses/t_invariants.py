"""Analysis ``t-invariants``: minimal-support transition invariants of a P/T net."""

from __future__ import annotations

from app.domain.contract import ElementRef
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure

from .incidence import incidence_of
from .invariants import SemiflowParameters, WeightedElement
from .semiflows import minimal_semiflows


class TInvariantsParameters(SemiflowParameters):
    """Options of the search for transition invariants."""


class TInvariant(DomainModel):
    """A transition invariant: firing these transitions, that many times, returns to the marking."""

    elements: tuple[WeightedElement, ...]


class TInvariantsResult(DomainModel):
    """The minimal-support invariants found, and how far the search went."""

    invariants: tuple[TInvariant, ...]
    total: int
    # False when the search stopped at its bound: there may be more invariants than listed.
    complete: bool
    # Transitions in no invariant cannot be part of any cyclic behaviour.
    uncovered_transitions: tuple[ElementRef, ...]


def t_invariants(
    *, structure: NetStructure, parameters: TInvariantsParameters
) -> TInvariantsResult:
    """Compute the minimal-support T-invariants: semiflows of the transposed incidence matrix."""
    incidence = incidence_of(structure=structure)
    transitions = incidence.transitions
    by_transition = tuple(
        tuple(row[column] for row in incidence.matrix) for column in range(len(transitions))
    )
    found = minimal_semiflows(matrix=by_transition, max_rows=parameters.max_rows)
    invariants = tuple(
        TInvariant(
            elements=tuple(
                WeightedElement(element=ref_of(node=transitions[position]), weight=weight)
                for position, weight in enumerate(flow)
                if weight
            )
        )
        for flow in found.flows
    )
    covered = {w.element.id for invariant in invariants for w in invariant.elements}
    return TInvariantsResult(
        invariants=invariants[: parameters.max_invariants],
        total=len(invariants),
        complete=found.complete,
        uncovered_transitions=tuple(ref_of(node=t) for t in transitions if t.id not in covered),
    )
