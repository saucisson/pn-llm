"""Rules that fuse twins: ``fuse-parallel-places`` and ``fuse-parallel-transitions``.

Two places with the same producers, the same consumers, the same weights and the same marking
always hold the same number of tokens, so one of them says nothing the other does not. Two
transitions with the same inputs and outputs enable and change the marking in the same way, so one
of them suffices (Berthelot, "Transformations and decompositions of nets", 1987).
"""

from __future__ import annotations

from app.domain.net_structure import NetStructure

from .driver import Merge, Step, reduce_with
from .result import ReductionComputation, ReductionParameters
from .working import WorkingNet

PARALLEL_PRESERVES = ("reachability", "deadlock_freedom", "liveness", "boundedness", "ltl")


def fuse_twins(*, groups: dict[object, list[str]], protected: frozenset[str]) -> tuple[Merge, ...]:
    """For each group of twins, keep one and list the others as merged into it.

    The twin kept is a protected one if there is one, else the first by id. Protected twins are
    never removed, so a group may keep several.
    """
    merges = []
    for members in groups.values():
        if len(members) < 2:  # noqa: PLR2004 - a twin needs a twin
            continue
        ordered = sorted(members)
        kept = next((m for m in ordered if m in protected), ordered[0])
        gone = tuple(m for m in ordered if m != kept and m not in protected)
        if gone:
            merges.append(Merge(merged=gone, into=kept))
    return tuple(merges)


def fuse_places(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Merge every group of parallel places in one application."""
    groups: dict[object, list[str]] = {}
    for place in net.places:
        key = (
            frozenset((t, net.post[t][place]) for t in net.producers[place]),
            frozenset((t, net.pre[t][place]) for t in net.consumers[place]),
            net.tokens[place],
        )
        groups.setdefault(key, []).append(place)
    merges = fuse_twins(groups=groups, protected=protected)
    if not merges:
        return None
    for merge in merges:
        for place in merge.merged:
            net.remove_place(place=place)
    return Step(removed=tuple(p for m in merges for p in m.merged), merges=merges)


def fuse_transitions(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Merge every group of parallel transitions in one application."""
    groups: dict[object, list[str]] = {}
    for transition in net.transitions:
        key = (frozenset(net.pre[transition].items()), frozenset(net.post[transition].items()))
        groups.setdefault(key, []).append(transition)
    merges = fuse_twins(groups=groups, protected=protected)
    if not merges:
        return None
    for merge in merges:
        for transition in merge.merged:
            net.remove_transition(transition=transition)
    return Step(removed=tuple(t for m in merges for t in m.merged), merges=merges)


def fuse_parallel_places(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Merge places that always hold the same tokens."""
    return reduce_with(
        rule_name="fuse-parallel-places",
        preserves=PARALLEL_PRESERVES,
        rule=fuse_places,
        structure=structure,
        parameters=parameters,
    )


def fuse_parallel_transitions(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Merge transitions that read and write the same places in the same way."""
    return reduce_with(
        rule_name="fuse-parallel-transitions",
        preserves=PARALLEL_PRESERVES,
        rule=fuse_transitions,
        structure=structure,
        parameters=parameters,
    )
