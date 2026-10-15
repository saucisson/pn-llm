"""Analysis ``conflict-sets``: groups of transitions that compete for the same input places."""

from __future__ import annotations

from pydantic import Field

from app.domain.contract import ElementRef
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure


class ConflictSetsParameters(DomainModel):
    """Options of the analysis."""

    # At most this many groups are listed, the largest first; the total is always given.
    max_groups: int = Field(default=200, ge=1, le=100_000)


class ConflictSet(DomainModel):
    """Transitions linked, directly or through others, by a shared input place."""

    transitions: tuple[ElementRef, ...]
    # The places they share, which are where the choice is made.
    shared_places: tuple[ElementRef, ...]


class ConflictSetsResult(DomainModel):
    """The groups of at least two transitions in structural conflict."""

    groups: tuple[ConflictSet, ...]
    total: int
    transitions_in_conflict: int
    transitions_without_conflict: int


def conflict_sets(
    *, structure: NetStructure, parameters: ConflictSetsParameters
) -> ConflictSetsResult:
    """Group transitions by shared input places (the connected parts of "shares an input")."""
    place_ids = {place.id for place in structure.places}
    consumers: dict[str, set[str]] = {}
    for arc in structure.arcs:
        if arc.source in place_ids:
            consumers.setdefault(arc.source, set()).add(arc.target)
    # Union by relabelling: every transition starts alone; sharing a place merges two groups.
    group_of = {t.id: {t.id} for t in structure.transitions}
    for sharing in consumers.values():
        merged: set[str] = set()
        for transition in sharing:
            merged |= group_of[transition]
        for transition in merged:
            group_of[transition] = merged
    members = {id(group): group for group in group_of.values()}
    nodes = {n.id: n for n in (*structure.places, *structure.transitions)}
    groups = []
    for group in members.values():
        if len(group) < 2:  # noqa: PLR2004 - a conflict needs two transitions
            continue
        shared = sorted(p for p, users in consumers.items() if len(users) > 1 and users <= group)
        groups.append(
            ConflictSet(
                transitions=tuple(ref_of(node=nodes[t]) for t in sorted(group)),
                shared_places=tuple(ref_of(node=nodes[p]) for p in shared),
            )
        )
    groups.sort(key=lambda g: (-len(g.transitions), g.transitions[0].id))
    in_conflict = sum(len(g.transitions) for g in groups)
    return ConflictSetsResult(
        groups=tuple(groups[: parameters.max_groups]),
        total=len(groups),
        transitions_in_conflict=in_conflict,
        transitions_without_conflict=len(structure.transitions) - in_conflict,
    )
