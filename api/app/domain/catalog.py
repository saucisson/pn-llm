"""The catalog of operations: every analysis and every reduction, found by name."""

from __future__ import annotations

from .analyses import ANALYSES
from .operations import OperationDefinition
from .reductions import REDUCTIONS

OPERATIONS: tuple[OperationDefinition, ...] = (*ANALYSES, *REDUCTIONS)


def find_operation(*, name: str) -> OperationDefinition | None:
    """Return the operation of that name, or None."""
    return next((op for op in OPERATIONS if op.name == name), None)
