"""Rules that remove transitions: ``remove-dead-transitions``, ``remove-self-loop-transitions``."""

from __future__ import annotations

from app.domain.analyses.dead_transitions import dead_transitions
from app.domain.net_structure import NetStructure
from app.domain.operations import NoParameters

from .driver import Step, reduce_with
from .result import ReductionComputation, ReductionParameters
from .working import WorkingNet

DEAD_PRESERVES = ("reachability", "deadlock_freedom", "liveness", "boundedness", "ltl")
# A self-loop transition keeps a marking from being a deadlock: removing it does not preserve that.
SELF_LOOP_PRESERVES = ("reachability", "boundedness")


def remove_dead(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Remove every unprotected dead transition in one application."""
    dead = dead_transitions(structure=net.structure(), parameters=NoParameters())
    doomed = tuple(sorted({t.id for t in dead.dead_transitions} - protected))
    if not doomed:
        return None
    for transition in doomed:
        net.remove_transition(transition=transition)
    return Step(removed=doomed)


def remove_self_loops(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Remove every unprotected transition whose firing changes no marking, in one application."""
    doomed = tuple(
        sorted(t for t in net.transitions if net.pre[t] == net.post[t] and t not in protected)
    )
    if not doomed:
        return None
    for transition in doomed:
        net.remove_transition(transition=transition)
    return Step(removed=doomed)


def remove_dead_transitions(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Remove the transitions that can never fire (the analysis ``dead-transitions``)."""
    return reduce_with(
        rule_name="remove-dead-transitions",
        preserves=DEAD_PRESERVES,
        rule=remove_dead,
        structure=structure,
        parameters=parameters,
    )


def remove_self_loop_transitions(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Remove the transitions that consume exactly what they produce."""
    return reduce_with(
        rule_name="remove-self-loop-transitions",
        preserves=SELF_LOOP_PRESERVES,
        rule=remove_self_loops,
        structure=structure,
        parameters=parameters,
    )
