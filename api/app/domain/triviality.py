"""Properties that hold or fail whatever the system does, found from its structure.

Language models readily propose properties that pass for no interesting reason: a condition on a
place that can never hold that many tokens, an implication whose premise is impossible, an
invariant the net's own invariants already give. Such a property is not wrong, it is empty:
saying it holds tells nothing about the system. This module evaluates a formula on what the
structure guarantees (bounds, place invariants, dead transitions) and reports what it finds,
without dropping the property (docs/analyses). It proves; it never guesses: when the structure
does not decide a part, that part is unknown.
"""

from __future__ import annotations

from typing import Literal

from .analyses.dead_transitions import DeadTransitionsResult
from .analyses.p_invariants import PInvariantsResult
from .analyses.place_bounds import PlaceBoundsResult
from .contract import FiniteBound
from .formula import (
    And,
    Compare,
    Constant,
    CtlUnary,
    Enabled,
    Expression,
    Formula,
    Implies,
    LtlUnary,
    Not,
    Or,
    TokenCount,
    Tokens,
    Truth,
    subexpressions,
)
from .models import DomainModel

type Known = bool | None  # always true, always false, or not decided by the structure


class StructuralFacts(DomainModel):
    """What the structure of the net guarantees; each part may be missing."""

    bounds: PlaceBoundsResult | None = None
    invariants: PInvariantsResult | None = None
    dead: DeadTransitionsResult | None = None


class Triviality(DomainModel):
    """One reason a property says nothing, and where in the formula it was found."""

    kind: Literal["vacuous_antecedent", "holds_in_every_state", "holds_in_no_state"]
    path: str
    explanation: str


def upper_bounds(*, facts: StructuralFacts) -> dict[str, int]:
    """Return the finite bound of each place the analysis listed."""
    if facts.bounds is None:
        return {}
    return {
        b.place.id: b.bound.value for b in facts.bounds.bounds if isinstance(b.bound, FiniteBound)
    }


def compare_known(*, cmp: str, low: int, high: int | None, value: int) -> Known:
    """Decide ``x cmp value`` for any ``x`` between ``low`` and ``high`` (None: no upper limit)."""
    if cmp == ">=":
        return True if low >= value else False if high is not None and high < value else None
    if cmp == ">":
        return True if low > value else False if high is not None and high <= value else None
    if cmp == "<=":
        return True if high is not None and high <= value else False if low > value else None
    if cmp == "<":
        return True if high is not None and high < value else False if low >= value else None
    if cmp == "==":
        return False if value < low or (high is not None and value > high) else None
    return True if value < low or (high is not None and value > high) else None  # !=


def sum_upper_bound(
    *, places: tuple[str, ...], facts: StructuralFacts, bounds: dict[str, int]
) -> int | None:
    """Bound a sum of places: by an invariant weighing each at least 1, or by their bounds."""
    candidates = []
    if facts.invariants is not None:
        for invariant in facts.invariants.invariants:
            weights = {w.element.id: w.weight for w in invariant.elements}
            if all(weights.get(p, 0) >= 1 for p in places):
                candidates.append(invariant.constant)
    if all(p in bounds for p in places):
        candidates.append(sum(bounds[p] for p in places))
    return min(candidates) if candidates else None


def known_value(  # noqa: PLR0911 - one branch per kind of expression
    *, expression: Expression, facts: StructuralFacts, bounds: dict[str, int]
) -> Known:
    """Evaluate an expression on what the structure guarantees."""
    if isinstance(expression, Truth):
        return expression.value
    if isinstance(expression, Tokens):
        return compare_known(
            cmp=expression.cmp, low=0, high=bounds.get(expression.place), value=expression.value
        )
    if isinstance(expression, Compare):
        if isinstance(expression.left, TokenCount) and isinstance(expression.right, Constant):
            high = sum_upper_bound(places=expression.left.places, facts=facts, bounds=bounds)
            return compare_known(cmp=expression.cmp, low=0, high=high, value=expression.right.value)
        return None
    if isinstance(expression, Enabled):
        dead = {t.id for t in facts.dead.dead_transitions} if facts.dead is not None else set()
        return False if expression.transition in dead else None
    if isinstance(expression, Not):
        inner = known_value(expression=expression.arg, facts=facts, bounds=bounds)
        return None if inner is None else not inner
    if isinstance(expression, And | Or):
        values = [known_value(expression=a, facts=facts, bounds=bounds) for a in expression.args]
        decisive = not isinstance(expression, And)
        if decisive in values:
            return decisive
        return (not decisive) if all(v is not None for v in values) else None
    if isinstance(expression, Implies):
        left = known_value(expression=expression.left, facts=facts, bounds=bounds)
        right = known_value(expression=expression.right, facts=facts, bounds=bounds)
        if left is False or right is True:
            return True
        return right if left is True else None
    if isinstance(expression, CtlUnary | LtlUnary) and expression.op not in {"AX", "EX", "X"}:
        # G, F, AG, EF... over an always-true (always-false) condition are true (false) too: the
        # initial state is a state, and every state has the same value.
        return known_value(expression=expression.arg, facts=facts, bounds=bounds)
    return None


def triviality_of(*, formula: Formula, facts: StructuralFacts) -> tuple[Triviality, ...]:
    """List why a property says nothing, if the structure shows it."""
    bounds = upper_bounds(facts=facts)
    found: list[Triviality] = []
    for located in subexpressions(expression=formula.ast, path=""):
        node = located.expression
        if (
            isinstance(node, Implies)
            and known_value(expression=node.left, facts=facts, bounds=bounds) is False
        ):
            found.append(
                Triviality(
                    kind="vacuous_antecedent",
                    path=f"{located.path}/left",
                    explanation=(
                        "the condition before '->' can never hold (a bound, an invariant or a dead "
                        "transition rules it out), so the implication is true whatever follows"
                    ),
                )
            )
    overall = known_value(expression=formula.ast, facts=facts, bounds=bounds)
    if overall is True:
        found.append(
            Triviality(
                kind="holds_in_every_state",
                path="",
                explanation=(
                    "the structure of the net already guarantees it (bounds, invariants, dead "
                    "transitions): it holds without checking the behaviour"
                ),
            )
        )
    elif overall is False:
        found.append(
            Triviality(
                kind="holds_in_no_state",
                path="",
                explanation="the structure of the net rules it out: it fails whatever it does",
            )
        )
    return tuple(found)
