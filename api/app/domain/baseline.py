"""Baseline B0: standard properties generated from the structure of a net, without a language model.

The bar a model must clear (docs/evaluation.md): a rule-based generator that writes the properties
an engineer would try first on any net. It is deterministic, takes the same budget (a number of
properties) as the other conditions and returns the same objects (``Formula``), so the same
checks, engines and measures apply to it.
"""

from __future__ import annotations

from pydantic import Field

from .analyses.p_invariants import PInvariantsResult
from .analyses.place_bounds import PlaceBoundsResult
from .contract import FiniteBound
from .formula import And, CtlUnary, Deadlock, Enabled, Expression, Formula, Not, Tokens
from .models import DomainModel
from .net_structure import NetStructure

# A marking this large is not written out as a home-state candidate: it would not be read.
MAX_PLACES_IN_HOME_STATE = 40
# Exclusions are looked for in invariants worth at most this much: one token to share.
MUTEX_CONSTANT = 1


class BaselineBudget(DomainModel):
    """How many properties the generator may return."""

    max_properties: int = Field(default=20, ge=1, le=1000)


class BaselineFacts(DomainModel):
    """The static-analysis facts the rules use; any of them may be missing."""

    invariants: PInvariantsResult | None = None
    bounds: PlaceBoundsResult | None = None


def baseline_properties(
    *, structure: NetStructure, facts: BaselineFacts, budget: BaselineBudget
) -> tuple[Formula, ...]:
    """Return the standard properties of a P/T net, at most ``budget`` of them, in a fixed order.

    Deadlock freedom comes first, then the other families in turns, so a small budget still covers
    every family. Within a family the order is the order of the ids.
    """
    deadlock_freedom = Formula(
        id="b0-deadlock-freedom",
        logic="ctl",
        ast=CtlUnary(op="AG", arg=Not(arg=Deadlock())),
        gloss="The system can always do something: no reachable marking is a deadlock.",
        origin="template",
    )
    home_state: list[Formula] = []
    if structure.kind == "pt" and 0 < len(structure.places) <= MAX_PLACES_IN_HOME_STATE:
        atoms: list[Expression] = [
            Tokens(place=node.id, cmp="==", value=node.tokens or 0) for node in structure.places
        ]
        initial: Expression = atoms[0] if len(atoms) == 1 else And(args=tuple(atoms))
        home_state.append(
            Formula(
                id="b0-home-state",
                logic="ctl",
                ast=CtlUnary(op="AG", arg=CtlUnary(op="EF", arg=initial)),
                gloss="From every reachable marking the initial marking can be reached again.",
                origin="template",
            )
        )

    finite = {}
    if facts.bounds is not None:
        finite = {
            item.place.id: item.bound.value
            for item in facts.bounds.bounds
            if isinstance(item.bound, FiniteBound)
        }
    bounded = [
        Formula(
            id=f"b0-bounded-{node.id}",
            logic="ctl",
            ast=CtlUnary(
                op="AG",
                arg=Tokens(
                    place=node.id, cmp="<=", value=max(finite.get(node.id, 1), node.tokens or 0)
                ),
            ),
            gloss=f"Place {node.id} never holds more than "
            f"{max(finite.get(node.id, 1), node.tokens or 0)} tokens.",
            origin="template",
        )
        for node in structure.places
    ]
    quasi_live = [
        Formula(
            id=f"b0-quasi-live-{node.id}",
            logic="ctl",
            ast=CtlUnary(op="EF", arg=Enabled(transition=node.id)),
            gloss=f"Transition {node.id} can fire in some reachable marking.",
            origin="template",
        )
        for node in structure.transitions
    ]
    exclusions: list[Formula] = []
    if facts.invariants is not None:
        seen: set[tuple[str, str]] = set()
        for invariant in facts.invariants.invariants:
            members = sorted(w.element.id for w in invariant.elements if w.weight == 1)
            if invariant.constant != MUTEX_CONSTANT:
                continue
            for index, first in enumerate(members):
                for second in members[index + 1 :]:
                    if (first, second) in seen:
                        continue
                    seen.add((first, second))
                    exclusions.append(
                        Formula(
                            id=f"b0-exclusion-{first}-{second}",
                            logic="ctl",
                            ast=CtlUnary(
                                op="AG",
                                arg=Not(
                                    arg=And(
                                        args=(
                                            Tokens(place=first, cmp=">=", value=1),
                                            Tokens(place=second, cmp=">=", value=1),
                                        )
                                    )
                                ),
                            ),
                            gloss=f"Places {first} and {second} are never marked together.",
                            origin="template",
                        )
                    )

    families = [exclusions, bounded, quasi_live, home_state]
    chosen: list[Formula] = [deadlock_freedom]
    position = 0
    while len(chosen) < budget.max_properties and any(position < len(f) for f in families):
        for family in families:
            if position < len(family) and len(chosen) < budget.max_properties:
                chosen.append(family[position])
        position += 1
    return tuple(chosen)
