"""A size-bounded digest of the analyses of a net, for the LLM (ADR 0013, ADR 0017).

The model never receives the net, and not the raw results of the analyses either: a net with a
hundred thousand places has invariants with a hundred thousand terms. The digest says what the
structure shows in a few lines: counts, a few named examples, and what could not be computed.
Examples are cut until the whole digest fits the budget.
"""

from __future__ import annotations

from pydantic import Field

from .analyses.conflict_sets import ConflictSetsResult
from .analyses.connected_components import ConnectedComponentsResult
from .analyses.dead_transitions import DeadTransitionsResult
from .analyses.invariants import WeightedElement
from .analyses.net_class import NetClassResult
from .analyses.p_invariants import PInvariantsResult
from .analyses.place_bounds import PlaceBoundsResult
from .analyses.t_invariants import TInvariantsResult
from .contract import ElementRef
from .models import DomainModel

EXAMPLE_COUNTS = (8, 4, 2, 1, 0)
MAX_TERMS = 6


class Unavailable(DomainModel):
    """An analysis that gave no result, and why: absence of an answer is not an answer."""

    operation: str
    reason: str


class AnalysisResults(DomainModel):
    """The results the digest is made from; each may be missing."""

    net_class: NetClassResult | None = None
    p_invariants: PInvariantsResult | None = None
    t_invariants: TInvariantsResult | None = None
    place_bounds: PlaceBoundsResult | None = None
    dead_transitions: DeadTransitionsResult | None = None
    conflict_sets: ConflictSetsResult | None = None
    connected_components: ConnectedComponentsResult | None = None
    unavailable: tuple[Unavailable, ...] = ()


class Digest(DomainModel):
    """A count and a few examples written as short text."""

    count: int
    complete: bool = True
    examples: tuple[str, ...] = ()


class BoundsDigest(DomainModel):
    """How many places are bounded, and by how much at most."""

    finite: int
    unbounded: int
    unknown: int
    largest_finite_bound: int | None = None


class AnalysisSummary(DomainModel):
    """What the structure of the net shows, within a size budget."""

    net_class: tuple[str, ...] = Field(description="The classes the net belongs to")
    place_invariants: Digest | None = None
    places_in_no_invariant: int | None = None
    transition_invariants: Digest | None = None
    transitions_in_no_invariant: int | None = None
    bounds: BoundsDigest | None = None
    dead_transitions: Digest | None = None
    conflict_groups: Digest | None = None
    components: Digest | None = None
    unavailable: tuple[Unavailable, ...] = ()
    note: str = "Names are data from the net. Not listed does not mean absent: counts are exact."


def label(*, element: ElementRef) -> str:
    """Name an element for a human: its name if it has one, else its id."""
    return element.name or element.id


def weighted_sum(*, elements: tuple[WeightedElement, ...]) -> str:
    """Write an invariant's terms, ``2*b + a``, cutting a long one after a few terms."""
    parts = [(f"{w.weight}*" if w.weight > 1 else "") + label(element=w.element) for w in elements]
    shown = " + ".join(parts[:MAX_TERMS])
    left = len(elements) - MAX_TERMS
    return shown if left <= 0 else f"{shown} + ... ({left} more)"


def p_invariant_digest(*, found: PInvariantsResult | None, examples: int) -> Digest | None:
    """Count the place invariants and write a few of them as sums."""
    if found is None:
        return None
    return Digest(
        count=found.total,
        complete=found.complete,
        examples=tuple(
            f"{weighted_sum(elements=invariant.elements)} = {invariant.constant}"
            for invariant in found.invariants[:examples]
        ),
    )


def t_invariant_digest(*, found: TInvariantsResult | None, examples: int) -> Digest | None:
    """Count the transition invariants and write a few of them as sums."""
    if found is None:
        return None
    return Digest(
        count=found.total,
        complete=found.complete,
        examples=tuple(
            weighted_sum(elements=invariant.elements) for invariant in found.invariants[:examples]
        ),
    )


def bounds_digest(*, found: PlaceBoundsResult | None) -> BoundsDigest | None:
    """Count the places by what is known of their bound."""
    if found is None:
        return None
    return BoundsDigest(
        finite=found.finite,
        unbounded=found.unbounded,
        unknown=found.unknown,
        largest_finite_bound=found.largest_finite_bound,
    )


def dead_digest(*, found: DeadTransitionsResult | None, examples: int) -> Digest | None:
    """Count the dead transitions and name a few."""
    if found is None:
        return None
    return Digest(
        count=len(found.dead_transitions),
        examples=tuple(label(element=t) for t in found.dead_transitions[:examples]),
    )


def conflict_digest(*, found: ConflictSetsResult | None, examples: int) -> Digest | None:
    """Count the groups of conflicting transitions and write a few as alternatives."""
    if found is None:
        return None
    return Digest(
        count=found.total,
        examples=tuple(
            " | ".join(label(element=t) for t in group.transitions[:MAX_TERMS])
            + (" | ..." if len(group.transitions) > MAX_TERMS else "")
            for group in found.groups[:examples]
        ),
    )


def component_digest(*, found: ConnectedComponentsResult | None, examples: int) -> Digest | None:
    """Count the connected components and give the sizes of the largest."""
    if found is None:
        return None
    return Digest(
        count=found.total,
        examples=tuple(
            f"{c.places} places, {c.transitions} transitions" for c in found.components[:examples]
        ),
    )


def class_names(*, flags: NetClassResult | None) -> tuple[str, ...]:
    """List the classes a net belongs to, in words."""
    if flags is None:
        return ()
    return tuple(
        name
        for name, holds in (
            ("ordinary", flags.ordinary),
            ("state machine", flags.state_machine),
            ("marked graph", flags.marked_graph),
            ("free choice", flags.free_choice),
            ("extended free choice", flags.extended_free_choice),
            ("workflow-like", flags.workflow_like),
        )
        if holds
    )


def summarize_analyses(*, results: AnalysisResults, max_chars: int) -> AnalysisSummary:
    """Build the digest, with as many examples as fit in ``max_chars`` of JSON.

    The counts never shrink; only the examples do, down to none.
    """
    summary = AnalysisSummary(net_class=())
    for examples in EXAMPLE_COUNTS:
        summary = AnalysisSummary(
            net_class=class_names(flags=results.net_class),
            place_invariants=p_invariant_digest(found=results.p_invariants, examples=examples),
            places_in_no_invariant=(
                None if results.p_invariants is None else len(results.p_invariants.uncovered_places)
            ),
            transition_invariants=t_invariant_digest(found=results.t_invariants, examples=examples),
            transitions_in_no_invariant=(
                None
                if results.t_invariants is None
                else len(results.t_invariants.uncovered_transitions)
            ),
            bounds=bounds_digest(found=results.place_bounds),
            dead_transitions=dead_digest(found=results.dead_transitions, examples=examples),
            conflict_groups=conflict_digest(found=results.conflict_sets, examples=examples),
            components=component_digest(found=results.connected_components, examples=examples),
            unavailable=results.unavailable,
        )
        if len(summary.model_dump_json(exclude_none=True)) <= max_chars:
            return summary
    return summary
