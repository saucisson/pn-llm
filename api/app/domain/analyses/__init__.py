"""The analyses: one module each, listed here in the catalog."""

from __future__ import annotations

from app.domain.operations import NoParameters, OperationDefinition

from .net_class import NetClassResult, net_class
from .p_invariants import PInvariantsParameters, PInvariantsResult, p_invariants

ANALYSES: tuple[OperationDefinition, ...] = (
    OperationDefinition(
        name="net-class",
        kind="analysis",
        summary="Structural classes: state machine, marked graph, free choice, workflow-like.",
        parameters_model=NoParameters,
        result_model=NetClassResult,
        compute=net_class,
    ),
    OperationDefinition(
        name="p-invariants",
        kind="analysis",
        summary="Minimal-support place invariants: weighted place sets with a constant token sum.",
        parameters_model=PInvariantsParameters,
        result_model=PInvariantsResult,
        compute=p_invariants,
    ),
)
OPERATIONS: tuple[OperationDefinition, ...] = ANALYSES


def find_operation(*, name: str) -> OperationDefinition | None:
    """Return the operation of that name, or None."""
    return next((op for op in OPERATIONS if op.name == name), None)
