"""Lifting a counterexample from a reduced net back to the net it came from.

A reduction says, for each transition of the reduced net that stands for a sequence of the
parent's, what that sequence is. Lifting a trace replaces each firing with its sequence, net by
net, from the reduced net up to the original. The lifted trace is then replayed by the platform
like any other: an expansion that did not hold would show up there.
"""

from __future__ import annotations

from .engine_check import initial_marking_of
from .engine_contract import Trace, TraceStep
from .errors import InvalidRequestError
from .inspection import ref_of
from .net_structure import NetStructure
from .operations import Lineage


def lift_trace(*, trace: Trace, chain: tuple[Lineage, ...], root: NetStructure) -> Trace:
    """Express a trace of a reduced net on the net the chain of reductions started from.

    ``chain`` lists the lineage links from the traced net up to the original, nearest first.
    A step with no expansion stands for itself. ``loop_start`` moves with the steps before it.

    Raises:
        InvalidRequestError: if a lifted step is not a transition of the original net.
    """
    steps = tuple(step.transition.id for step in trace.steps)
    loop_start = trace.loop_start
    for link in chain:
        expansions = {item.transition: item.original for item in link.expansions}
        lifted = tuple(original for step in steps for original in expansions.get(step, (step,)))
        if loop_start is not None:
            loop_start = sum(len(expansions.get(step, (step,))) for step in steps[:loop_start])
        steps = lifted
    nodes = {node.id: node for node in root.transitions}
    missing = [step for step in steps if step not in nodes]
    if missing:
        raise InvalidRequestError(
            f"The lifted trace cites {missing[0]!r}, not a transition of the original net"
        )
    return Trace(
        formula_id=trace.formula_id,
        net_id=root.net_id,
        initial_marking=initial_marking_of(structure=root),
        steps=tuple(TraceStep(transition=ref_of(node=nodes[step])) for step in steps),
        loop_start=loop_start,
    )
