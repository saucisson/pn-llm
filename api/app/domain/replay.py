"""Replay a sequence of firings on a P/T net, and evaluate a state condition on a marking.

Replay is how the platform checks an engine's counterexample without trusting the engine
(docs/json-contract.md): the trace is fired transition by transition on the net, and a state
formula can be evaluated on the marking it reaches.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping

from .contract import ElementRef, Marking, MarkingEntry, PageRequest
from .errors import InvalidRequestError
from .formula import (
    And,
    Compare,
    Constant,
    Deadlock,
    Enabled,
    Expression,
    Implies,
    Not,
    Or,
    TokenCount,
    Tokens,
    Truth,
)
from .models import DomainModel
from .net_structure import NetStructure, StructureNode
from .pagination import decode_cursor

COMPARISONS = {
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    ">": operator.gt,
}


class ReplayRequest(DomainModel):
    """Body of ``POST /v1/nets/{id}/replay``."""

    steps: tuple[str, ...]
    # Without it the replay starts from the initial marking of the net.
    initial_marking: Marking | None = None
    # A condition on one marking (no temporal operator), evaluated on the final marking.
    state_formula: Expression | None = None
    # Which of the successive markings to return: the first one is the marking before step 0.
    page: PageRequest = PageRequest()


class MissingTokens(DomainModel):
    """A place that holds fewer tokens than a firing needs."""

    place: ElementRef
    needed: int
    available: int


class ReplayFailure(DomainModel):
    """Where a replay stopped: the firing that was not enabled and what was missing."""

    step: int
    transition: ElementRef
    missing: tuple[MissingTokens, ...]


class ReplayResult(DomainModel):
    """Outcome of a replay."""

    valid: bool
    # Number of firings that succeeded; equal to the length of the trace when it is valid.
    replayed: int
    failure: ReplayFailure | None
    final_marking: Marking
    # The window of successive markings requested by ``page``: marking number ``markings_from + i``
    # is the one after ``markings_from + i`` firings. ``markings_total`` is ``replayed + 1``.
    markings_from: int
    markings_total: int
    markings: tuple[Marking, ...]
    state_formula_holds: bool | None = None


def holds(  # noqa: PLR0911 - one return per kind of node of the formula tree
    *, expression: Expression, tokens: Mapping[str, int], structure: NetStructure
) -> bool:
    """Evaluate a state condition on a marking.

    Raises:
        InvalidRequestError: if the formula has a temporal operator.
    """
    match expression:
        case Tokens():
            return bool(
                COMPARISONS[expression.cmp](tokens.get(expression.place, 0), expression.value)
            )
        case Compare():
            sides = []
            for term in (expression.left, expression.right):
                if isinstance(term, TokenCount):
                    sides.append(sum(tokens.get(place, 0) for place in term.places))
                elif isinstance(term, Constant):
                    sides.append(term.value)
            return bool(COMPARISONS[expression.cmp](sides[0], sides[1]))
        case Enabled():
            return enabled(transition=expression.transition, tokens=tokens, structure=structure)
        case Deadlock():
            return not any(
                enabled(transition=node.id, tokens=tokens, structure=structure)
                for node in structure.transitions
            )
        case Truth():
            return expression.value
        case Not():
            return not holds(expression=expression.arg, tokens=tokens, structure=structure)
        case And():
            return all(
                holds(expression=arg, tokens=tokens, structure=structure) for arg in expression.args
            )
        case Or():
            return any(
                holds(expression=arg, tokens=tokens, structure=structure) for arg in expression.args
            )
        case Implies():
            return not holds(
                expression=expression.left, tokens=tokens, structure=structure
            ) or holds(expression=expression.right, tokens=tokens, structure=structure)
        case _:
            message = f"operator {expression.op} is temporal: only a state condition is evaluated"
            raise InvalidRequestError(message)


def enabled(*, transition: str, tokens: Mapping[str, int], structure: NetStructure) -> bool:
    """Tell whether a transition can fire in a marking."""
    return all(
        tokens.get(arc.source, 0) >= (arc.weight or 1)
        for arc in structure.arcs
        if arc.target == transition
    )


def marking_of(*, tokens: Mapping[str, int], places: dict[str, StructureNode]) -> Marking:
    """Build the sparse marking for a token map."""
    return Marking(
        entries=tuple(
            MarkingEntry(
                place=ElementRef(id=place, name=places[place].name, kind="place"), tokens=count
            )
            for place, count in tokens.items()
            if count > 0
        )
    )


def replay(  # noqa: PLR0912 - one linear pass: validate, index arcs, fire, snapshot
    *, structure: NetStructure, request: ReplayRequest
) -> ReplayResult:
    """Fire the transitions of ``request.steps`` in order, from the starting marking.

    Raises:
        InvalidRequestError: if the net is not P/T, an id is not of the right kind, or the cursor
            is invalid.
    """
    if structure.kind != "pt":
        raise InvalidRequestError("Replay needs a P/T net")
    places = {node.id: node for node in structure.places}
    transitions = {node.id: node for node in structure.transitions}
    if request.initial_marking is None:
        tokens = {node.id: node.tokens or 0 for node in structure.places}
    else:
        tokens = dict.fromkeys(places, 0)
        for entry in request.initial_marking.entries:
            if entry.place.id not in places:
                raise InvalidRequestError(
                    f"Unknown place in the initial marking: {entry.place.id!r}"
                )
            tokens[entry.place.id] = entry.tokens
    for step in request.steps:
        if step not in transitions:
            raise InvalidRequestError(f"{step!r} is not a transition of the net")
    pre: dict[str, list[tuple[str, int]]] = {}
    post: dict[str, list[tuple[str, int]]] = {}
    for arc in structure.arcs:
        if arc.target in transitions:
            pre.setdefault(arc.target, []).append((arc.source, arc.weight or 1))
        else:
            post.setdefault(arc.source, []).append((arc.target, arc.weight or 1))

    start = 0 if request.page.cursor is None else decode_cursor(cursor=request.page.cursor)
    window = range(start, start + request.page.limit)
    snapshots: list[Marking] = [marking_of(tokens=tokens, places=places)] if 0 in window else []
    failure = None
    replayed = 0
    for index, step in enumerate(request.steps):
        missing = tuple(
            MissingTokens(
                place=ElementRef(id=place, name=places[place].name, kind="place"),
                needed=weight,
                available=tokens[place],
            )
            for place, weight in pre.get(step, ())
            if tokens[place] < weight
        )
        if missing:
            node = transitions[step]
            failure = ReplayFailure(
                step=index,
                transition=ElementRef(id=node.id, name=node.name, kind="transition"),
                missing=missing,
            )
            break
        for place, weight in pre.get(step, ()):
            tokens[place] -= weight
        for place, weight in post.get(step, ()):
            tokens[place] += weight
        replayed += 1
        if replayed in window:
            snapshots.append(marking_of(tokens=tokens, places=places))

    holds_at_end = None
    if request.state_formula is not None and failure is None:
        holds_at_end = holds(expression=request.state_formula, tokens=tokens, structure=structure)
    return ReplayResult(
        valid=failure is None,
        replayed=replayed,
        failure=failure,
        final_marking=marking_of(tokens=tokens, places=places),
        markings_from=start,
        markings_total=replayed + 1,
        markings=tuple(snapshots),
        state_formula_holds=holds_at_end,
    )
