"""Faults injected in a P/T net: the mutants a property set is judged on (measures M5 and M6).

Each operator makes one small change of the kind a modelling mistake makes: an arc forgotten or
added, a weight or an initial marking off by one, a transition left out. Mutants are chosen
deterministically from a seed, so every condition is judged on the same ones. Whether a mutant
differs from the original is not decided here: engines decide, and what they cannot decide is
reported as undecided (``mutation_score``).
"""

from __future__ import annotations

import random
from typing import Literal

from .models import DomainModel
from .net_structure import NetStructure, StructureArc

MutationOperator = Literal[
    "remove_arc", "add_arc", "change_weight", "change_marking", "remove_transition"
]
OPERATORS: tuple[MutationOperator, ...] = (
    "remove_arc",
    "add_arc",
    "change_weight",
    "change_marking",
    "remove_transition",
)
# Drawing a new arc may meet an existing one: give up after this many draws per wanted mutant.
DRAWS_PER_ADDED_ARC = 20
HALF = 0.5


class Mutant(DomainModel):
    """A net with one injected fault, and what was changed (ids as in the original net)."""

    operator: MutationOperator
    description: str
    changed: tuple[str, ...]
    structure: NetStructure


def with_arcs(*, structure: NetStructure, arcs: tuple[StructureArc, ...]) -> NetStructure:
    """Return the structure with these arcs."""
    return structure.model_copy(update={"arcs": arcs})


def remove_arc_mutants(*, structure: NetStructure) -> list[Mutant]:
    """One mutant per arc: the arc is forgotten."""
    return [
        Mutant(
            operator="remove_arc",
            description=f"arc {arc.source} -> {arc.target} removed",
            changed=(arc.source, arc.target),
            structure=with_arcs(
                structure=structure, arcs=tuple(a for a in structure.arcs if a != arc)
            ),
        )
        for arc in structure.arcs
    ]


def change_weight_mutants(*, structure: NetStructure) -> list[Mutant]:
    """One mutant per arc: its weight is one more."""
    return [
        Mutant(
            operator="change_weight",
            description=(
                f"weight of arc {arc.source} -> {arc.target} changed "
                f"from {arc.weight or 1} to {(arc.weight or 1) + 1}"
            ),
            changed=(arc.source, arc.target),
            structure=with_arcs(
                structure=structure,
                arcs=tuple(
                    a.model_copy(update={"weight": (arc.weight or 1) + 1}) if a == arc else a
                    for a in structure.arcs
                ),
            ),
        )
        for arc in structure.arcs
    ]


def change_marking_mutants(*, structure: NetStructure) -> list[Mutant]:
    """One mutant per place: it starts with one more token."""
    return [
        Mutant(
            operator="change_marking",
            description=(
                f"initial marking of {place.id} changed from {place.tokens or 0} "
                f"to {(place.tokens or 0) + 1}"
            ),
            changed=(place.id,),
            structure=structure.model_copy(
                update={
                    "places": tuple(
                        p.model_copy(update={"tokens": (place.tokens or 0) + 1})
                        if p.id == place.id
                        else p
                        for p in structure.places
                    )
                }
            ),
        )
        for place in structure.places
    ]


def remove_transition_mutants(*, structure: NetStructure) -> list[Mutant]:
    """One mutant per transition: it is left out, with its arcs."""
    return [
        Mutant(
            operator="remove_transition",
            description=f"transition {transition.id} removed",
            changed=(transition.id,),
            structure=structure.model_copy(
                update={
                    "transitions": tuple(t for t in structure.transitions if t.id != transition.id),
                    "arcs": tuple(
                        a for a in structure.arcs if transition.id not in {a.source, a.target}
                    ),
                }
            ),
        )
        for transition in structure.transitions
    ]


def add_arc_mutants(*, structure: NetStructure, wanted: int, rng: random.Random) -> list[Mutant]:
    """Up to ``wanted`` mutants, each with one new arc of weight 1."""
    if not structure.places or not structure.transitions:
        return []
    linked = {(a.source, a.target) for a in structure.arcs}
    drawn: set[tuple[str, str]] = set()
    found: list[Mutant] = []
    for _ in range(wanted * DRAWS_PER_ADDED_ARC):
        if len(found) >= wanted:
            break
        place = rng.choice(structure.places).id
        transition = rng.choice(structure.transitions).id
        ends = (place, transition) if rng.random() < HALF else (transition, place)
        if ends in linked or ends in drawn:
            continue
        drawn.add(ends)
        new = StructureArc(
            id=f"mutant:{ends[0]}->{ends[1]}", source=ends[0], target=ends[1], weight=1
        )
        found.append(
            Mutant(
                operator="add_arc",
                description=f"arc {ends[0]} -> {ends[1]} added",
                changed=ends,
                structure=with_arcs(structure=structure, arcs=(*structure.arcs, new)),
            )
        )
    return found


def mutants_of(
    *,
    structure: NetStructure,
    operators: tuple[MutationOperator, ...],
    per_operator: int,
    seed: str,
) -> tuple[Mutant, ...]:
    """Return up to ``per_operator`` mutants for each operator, the same for the same seed.

    Only P/T nets are mutated; any other kind of net has no mutant.
    """
    if structure.kind != "pt":
        return ()
    found: list[Mutant] = []
    for operator in operators:
        rng = random.Random(f"{seed}/{operator}")  # noqa: S311 - reproducibility, not security
        if operator == "add_arc":
            found.extend(add_arc_mutants(structure=structure, wanted=per_operator, rng=rng))
            continue
        candidates = {
            "remove_arc": remove_arc_mutants,
            "change_weight": change_weight_mutants,
            "change_marking": change_marking_mutants,
            "remove_transition": remove_transition_mutants,
        }[operator](structure=structure)
        rng.shuffle(candidates)
        found.extend(candidates[:per_operator])
    return tuple(found)
