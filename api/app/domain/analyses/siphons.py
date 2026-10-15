"""Analyses ``minimal-siphons`` and ``minimal-traps``: sets of places closed under the flow rule.

A siphon is a set of places ``S`` such that every transition that puts a token in ``S`` also takes
one from ``S``: once empty, it stays empty. A trap is the dual: every transition that takes a token
from ``S`` also puts one back, so once marked, it stays marked. Both searches branch on the places
that could repair a violated transition, and keep only the minimal sets.
"""

from __future__ import annotations

from pydantic import Field

from app.domain.contract import ElementRef
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure


class SiphonParameters(DomainModel):
    """Options of the search: the enumeration is exponential in the worst case."""

    # At most this many sets are listed; the total found is always given.
    max_results: int = Field(default=100, ge=1, le=10_000)
    # The search stops after this many branching steps and says so.
    max_steps: int = Field(default=200_000, ge=1, le=100_000_000)


class MinimalSiphonsParameters(SiphonParameters):
    """Options of the search for minimal siphons."""


class MinimalTrapsParameters(SiphonParameters):
    """Options of the search for minimal traps."""


class PlaceSet(DomainModel):
    """A set of places, and whether it holds a token in the initial marking."""

    places: tuple[ElementRef, ...]
    initially_marked: bool


class SiphonsResult(DomainModel):
    """The minimal siphons found."""

    sets: tuple[PlaceSet, ...]
    total: int
    # False when the search stopped at its bound: there may be more.
    complete: bool


class TrapsResult(DomainModel):
    """The minimal traps found."""

    sets: tuple[PlaceSet, ...]
    total: int
    # False when the search stopped at its bound: there may be more.
    complete: bool


class Guard(DomainModel):
    """If a set holds a place of ``entering`` it must also hold a place of ``repairing``."""

    entering: frozenset[str]
    repairing: frozenset[str]


class ClosedSets(DomainModel):
    """The raw result of a search, before it is dressed with element references."""

    sets: tuple[frozenset[str], ...]
    complete: bool


def closed_sets(
    *, guards: tuple[Guard, ...], places: tuple[str, ...], max_steps: int
) -> ClosedSets:
    """Return the minimal non-empty sets of places that respect every guard.

    A siphon has one guard per transition (outputs entering, inputs repairing), a trap the
    opposite. The search starts from each place and, at a violated guard, branches on the places
    that repair it.
    """
    found: list[frozenset[str]] = []
    steps = 0
    complete = True
    for seed in places:
        pending = [frozenset({seed})]
        while pending:
            current = pending.pop()
            steps += 1
            if steps > max_steps:
                complete = False
                break
            if any(known <= current for known in found):
                continue  # a smaller set exists already: this branch cannot be minimal
            violated = next(
                (
                    guard.repairing
                    for guard in guards
                    if guard.entering & current and not guard.repairing & current
                ),
                None,
            )
            if violated is None:
                found = [known for known in found if not current <= known]
                found.append(current)
            else:
                pending.extend(current | {place} for place in sorted(violated))
        if not complete:
            break
    return ClosedSets(
        sets=tuple(sorted(found, key=lambda s: (len(s), sorted(s)))), complete=complete
    )


class FoundSets(DomainModel):
    """Sets found by a search, as the operations report them."""

    sets: tuple[PlaceSet, ...]
    total: int
    complete: bool


def place_sets(
    *, structure: NetStructure, reverse: bool, parameters: SiphonParameters
) -> FoundSets:
    """Find the minimal siphons (or, reversed, the minimal traps) and dress them."""
    place_ids = {place.id for place in structure.places}
    inputs: dict[str, set[str]] = {t.id: set() for t in structure.transitions}
    outputs: dict[str, set[str]] = {t.id: set() for t in structure.transitions}
    for arc in structure.arcs:
        if arc.source in place_ids:
            inputs[arc.target].add(arc.source)
        else:
            outputs[arc.source].add(arc.target)
    guards = tuple(
        Guard(
            entering=frozenset(inputs[t] if reverse else outputs[t]),
            repairing=frozenset(outputs[t] if reverse else inputs[t]),
        )
        for t in inputs
    )
    found = closed_sets(
        guards=guards,
        places=tuple(place.id for place in structure.places),
        max_steps=parameters.max_steps,
    )
    nodes = {place.id: place for place in structure.places}
    dressed = tuple(
        PlaceSet(
            places=tuple(ref_of(node=nodes[place_id]) for place_id in sorted(members)),
            initially_marked=any((nodes[place_id].tokens or 0) > 0 for place_id in members),
        )
        for members in found.sets
    )
    return FoundSets(
        sets=dressed[: parameters.max_results], total=len(dressed), complete=found.complete
    )


def minimal_siphons(
    *, structure: NetStructure, parameters: MinimalSiphonsParameters
) -> SiphonsResult:
    """Compute the minimal siphons of a P/T net."""
    found = place_sets(structure=structure, reverse=False, parameters=parameters)
    return SiphonsResult(sets=found.sets, total=found.total, complete=found.complete)


def minimal_traps(*, structure: NetStructure, parameters: MinimalTrapsParameters) -> TrapsResult:
    """Compute the minimal traps of a P/T net."""
    found = place_sets(structure=structure, reverse=True, parameters=parameters)
    return TrapsResult(sets=found.sets, total=found.total, complete=found.complete)
