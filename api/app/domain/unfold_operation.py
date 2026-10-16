"""Unfolding as an operation: a symmetric net becomes the P/T net it stands for (ADR 0014).

It is registered with the reductions because it does what a reduction does to the platform: it
stores a new net linked to its parent. It keeps the behaviour of the net (every property of the
colored net is a property of the unfolded one, about its unfolded places and transitions) and the
mapping tells which unfolded elements stand for which colored place and color, transition and
binding (docs/colored-nets.md).
"""

from __future__ import annotations

from pydantic import Field

from .errors import InvalidRequestError
from .net_document import NetDocument
from .net_structure import NetStructure
from .operations import OperationDefinition
from .reductions.result import DocumentComputation, ReductionResult
from .unfolding import UnfoldingMapping, UnfoldLimits, unfold

UNFOLD_PRESERVES = ("reachability", "deadlock_freedom", "liveness", "boundedness", "ltl")


class UnfoldParameters(UnfoldLimits):
    """The size limits of the unfolding (``protected`` and the like do not apply)."""

    protected: tuple[str, ...] = Field(default=(), description="Ignored: nothing is merged")


class UnfoldResult(ReductionResult):
    """The answer of the unfolding: the usual fields of a reduction and the mapping."""

    mapping: UnfoldingMapping


def unfold_net(
    *, structure: NetStructure, parameters: UnfoldParameters, document: NetDocument | None
) -> DocumentComputation:
    """Unfold the net.

    Raises:
        InvalidRequestError: if the document is missing or the net cannot be unfolded.
    """
    if document is None:
        raise InvalidRequestError("Unfolding needs the net document")
    unfolded = unfold(
        document=document,
        net_id=structure.net_id,
        limits=UnfoldLimits(
            max_places=parameters.max_places,
            max_transitions=parameters.max_transitions,
            max_arcs=parameters.max_arcs,
        ),
    )
    return DocumentComputation(
        result=UnfoldResult(
            rule="unfold",
            changed=True,
            applications=len(unfolded.mapping.transitions),
            preserves=UNFOLD_PRESERVES,
            mapping=unfolded.mapping,
        ),
        document=unfolded.document,
    )


UNFOLD = OperationDefinition(
    name="unfold",
    kind="reduction",
    summary="Unfold a colored net into the P/T net it stands for, with the mapping.",
    parameters_model=UnfoldParameters,
    result_model=UnfoldResult,
    compute=unfold_net,
    preserves=UNFOLD_PRESERVES,
    supports_colored=True,
    uses_document=True,
)
