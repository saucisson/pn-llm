"""Lifting a counterexample from a reduced net back to the net it came from.

A reduction says, for each transition of the reduced net that stands for a sequence of the
parent's, what that sequence is. Lifting a trace replaces each firing with its sequence, net by
net, from the reduced net up to the original. The lifted trace is then replayed by the platform
like any other: an expansion that did not hold would show up there.
"""

from __future__ import annotations

from .contract import Assignment
from .engine_check import initial_marking_of
from .engine_contract import Trace, TraceStep
from .errors import InvalidRequestError
from .inspection import ref_of
from .net_structure import NetStructure
from .operations import Lineage, LineageExpansion

type LiftedStep = tuple[str, tuple[Assignment, ...]]


def expand_step(
    *, step: LiftedStep, expansions: dict[str, LineageExpansion]
) -> tuple[LiftedStep, ...]:
    """Replace a step by what it stands for in the parent (itself when it has no expansion)."""
    item = expansions.get(step[0])
    if item is None:
        return (step,)
    # A binding belongs to a single colored transition, not to a sequence of them.
    binding = item.binding if len(item.original) == 1 else ()
    return tuple((original, binding) for original in item.original)


def lift_trace(*, trace: Trace, chain: tuple[Lineage, ...], root: NetStructure) -> Trace:
    """Express a trace of a reduced net on the net the chain of reductions started from.

    ``chain`` lists the lineage links from the traced net up to the original, nearest first.
    A step with no expansion stands for itself. ``loop_start`` moves with the steps before it.

    Raises:
        InvalidRequestError: if a lifted step is not a transition of the original net.
    """
    steps = tuple((step.transition.id, step.binding or ()) for step in trace.steps)
    loop_start = trace.loop_start
    for link in chain:
        expansions = {item.transition: item for item in link.expansions}

        lifted = tuple(
            part for step in steps for part in expand_step(step=step, expansions=expansions)
        )
        if loop_start is not None:
            loop_start = sum(
                len(expand_step(step=step, expansions=expansions)) for step in steps[:loop_start]
            )
        steps = lifted
    nodes = {node.id: node for node in root.transitions}
    missing = [step for step, _ in steps if step not in nodes]
    if missing:
        raise InvalidRequestError(
            f"The lifted trace cites {missing[0]!r}, not a transition of the original net"
        )
    return Trace(
        formula_id=trace.formula_id,
        net_id=root.net_id,
        initial_marking=initial_marking_of(structure=root),
        steps=tuple(
            TraceStep(transition=ref_of(node=nodes[step]), binding=binding or None)
            for step, binding in steps
        ),
        loop_start=loop_start,
    )
