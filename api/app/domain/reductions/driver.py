"""The loop every reduction rule shares: apply it until it stops applying, and say what changed."""

from __future__ import annotations

from typing import Protocol

from app.domain.contract import ElementRef
from app.domain.errors import InvalidRequestError
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure, StructureNode

from .result import (
    MergedElements,
    ReductionComputation,
    ReductionParameters,
    ReductionResult,
    TransitionExpansion,
)
from .working import WorkingNet


class Merge(DomainModel):
    """Elements replaced by one of them, which stays (ids of the net before the step)."""

    merged: tuple[str, ...]
    into: str


class Expand(DomainModel):
    """From now on a firing of ``transition`` stands for firing ``replaces``, in order.

    ``replaces`` are transitions of the net before the step; the driver composes the expansions
    of successive steps, so that the final one is in terms of the net the rule started from.
    """

    transition: str
    replaces: tuple[str, ...]


class Step(DomainModel):
    """What one application of a rule did, as ids of the net before it."""

    removed: tuple[str, ...] = ()
    merges: tuple[Merge, ...] = ()
    expansions: tuple[Expand, ...] = ()


class Rule(Protocol):
    """A reduction rule: rewrites the working net once and says what it did."""

    def __call__(self, *, net: WorkingNet, protected: frozenset[str]) -> Step | None:
        """Apply the rule somewhere it applies, sparing protected elements, or return None."""
        ...


def refs_of(*, nodes: dict[str, StructureNode], ids: tuple[str, ...]) -> tuple[ElementRef, ...]:
    """Cite elements of the original net by their ids."""
    return tuple(ref_of(node=nodes[identifier]) for identifier in ids)


def reduce_with(
    *,
    rule_name: str,
    preserves: tuple[str, ...],
    rule: Rule,
    structure: NetStructure,
    parameters: ReductionParameters,
) -> ReductionComputation:
    """Apply ``rule`` to a copy of the net until it no longer applies (or ``max_applications``).

    ``rule`` rewrites the working net and returns what it did, or ``None`` when no place or
    transition of the net allows it. It must leave protected elements alone.

    Raises:
        InvalidRequestError: if a protected id is not an element of the net.
    """
    known = {node.id for node in (*structure.places, *structure.transitions)}
    unknown = sorted(set(parameters.protected) - known)
    if unknown:
        raise InvalidRequestError(f"Protected ids are not in the net: {unknown[:5]}")
    nodes = {node.id: node for node in (*structure.places, *structure.transitions)}
    protected = frozenset(parameters.protected)
    net = WorkingNet(structure=structure)
    removed: list[str] = []
    merged: list[Merge] = []
    expansions: dict[str, tuple[str, ...]] = {}
    applications = 0
    while parameters.max_applications is None or applications < parameters.max_applications:
        step = rule(net=net, protected=protected)
        if step is None:
            break
        applications += 1
        removed.extend(step.removed)
        merged.extend(step.merges)
        for expand in step.expansions:
            expansions[expand.transition] = tuple(
                original for name in expand.replaces for original in expansions.get(name, (name,))
            )
    if applications > 0 and (not net.places or not net.transitions):
        applications = 0
        note = "The reduction would leave a net with no place or no transition: nothing was done"
    else:
        note = "The rule applies nowhere in this net, given the protected elements"
    if applications == 0:
        return ReductionComputation(
            result=ReductionResult(
                rule=rule_name,
                changed=False,
                applications=0,
                preserves=preserves,
                note=note,
            )
        )

    return ReductionComputation(
        result=ReductionResult(
            rule=rule_name,
            changed=True,
            applications=applications,
            removed=refs_of(nodes=nodes, ids=tuple(removed)),
            merged=tuple(
                MergedElements(
                    merged=refs_of(nodes=nodes, ids=merge.merged),
                    into=ref_of(node=nodes[merge.into]),
                )
                for merge in merged
            ),
            expansions=tuple(
                TransitionExpansion(
                    transition=ref_of(node=nodes[t]), original=refs_of(nodes=nodes, ids=original)
                )
                for t, original in sorted(expansions.items())
            ),
            preserves=preserves,
        ),
        reduced=net.structure(),
    )
