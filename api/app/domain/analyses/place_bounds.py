"""Analysis ``place-bounds``: bounds on the tokens of each place that follow from the structure."""

from __future__ import annotations

from pydantic import Field

from app.domain.contract import Bound, ElementRef, FiniteBound, UnboundedBound, UnknownBound
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure

from .incidence import incidence_of
from .semiflows import minimal_semiflows


class PlaceBoundsParameters(DomainModel):
    """Options of the analysis."""

    # Stop the invariant search when its working set grows beyond this many rows.
    max_rows: int = Field(default=20_000, ge=1, le=1_000_000)
    # At most this many places are listed; the counts always cover every place.
    max_places: int = Field(default=500, ge=1, le=100_000)


class PlaceBound(DomainModel):
    """The bound of one place."""

    place: ElementRef
    bound: Bound


class PlaceBoundsResult(DomainModel):
    """Bounds from the P-invariants: a place in an invariant holds at most constant / weight."""

    bounds: tuple[PlaceBound, ...]
    total: int
    finite: int
    unbounded: int
    unknown: int
    # The largest of the finite bounds over every place, listed or not.
    largest_finite_bound: int | None
    # False when the invariant search stopped at its bound: some places may be bounded after all.
    complete: bool


def place_bounds(
    *, structure: NetStructure, parameters: PlaceBoundsParameters
) -> PlaceBoundsResult:
    """Bound each place by its P-invariants, and mark as unbounded what a source transition feeds.

    A place is unbounded when a transition without input places, always enabled, puts tokens in
    it. A place in no invariant and not fed that way is unknown: this analysis proves bounds, it
    does not disprove them.
    """
    incidence = incidence_of(structure=structure)
    found = minimal_semiflows(matrix=incidence.matrix, max_rows=parameters.max_rows)
    place_ids = {place.id for place in incidence.places}
    with_inputs = {arc.target for arc in structure.arcs if arc.source in place_ids}
    source_transitions = {t.id for t in incidence.transitions} - with_inputs
    fed_by_source = {arc.target for arc in structure.arcs if arc.source in source_transitions}
    bounds: list[PlaceBound] = []
    for position, place in enumerate(incidence.places):
        candidates = [
            sum(w * (incidence.places[q].tokens or 0) for q, w in enumerate(flow)) // flow[position]
            for flow in found.flows
            if flow[position] > 0
        ]
        bound: Bound
        if place.id in fed_by_source:
            bound = UnboundedBound()
        elif candidates:
            bound = FiniteBound(value=min(candidates))
        else:
            bound = UnknownBound()
        bounds.append(PlaceBound(place=ref_of(node=place), bound=bound))
    return PlaceBoundsResult(
        bounds=tuple(bounds[: parameters.max_places]),
        total=len(bounds),
        finite=sum(isinstance(b.bound, FiniteBound) for b in bounds),
        unbounded=sum(isinstance(b.bound, UnboundedBound) for b in bounds),
        unknown=sum(isinstance(b.bound, UnknownBound) for b in bounds),
        largest_finite_bound=max(
            (b.bound.value for b in bounds if isinstance(b.bound, FiniteBound)), default=None
        ),
        complete=found.complete,
    )
