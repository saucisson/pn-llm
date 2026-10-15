"""The reduction rules: one module of rules each, listed here in the catalog."""

from __future__ import annotations

from app.domain.operations import OperationDefinition

from .parallel import PARALLEL_PRESERVES, fuse_parallel_places, fuse_parallel_transitions
from .removals import (
    DEAD_PRESERVES,
    SELF_LOOP_PRESERVES,
    remove_dead_transitions,
    remove_self_loop_transitions,
)
from .result import ReductionParameters, ReductionResult

REDUCTIONS: tuple[OperationDefinition, ...] = (
    OperationDefinition(
        name="fuse-parallel-places",
        kind="reduction",
        summary="Merge places with the same producers, consumers, weights and marking.",
        parameters_model=ReductionParameters,
        result_model=ReductionResult,
        compute=fuse_parallel_places,
        preserves=PARALLEL_PRESERVES,
    ),
    OperationDefinition(
        name="fuse-parallel-transitions",
        kind="reduction",
        summary="Merge transitions with the same input and output places and weights.",
        parameters_model=ReductionParameters,
        result_model=ReductionResult,
        compute=fuse_parallel_transitions,
        preserves=PARALLEL_PRESERVES,
    ),
    OperationDefinition(
        name="remove-dead-transitions",
        kind="reduction",
        summary="Remove the transitions that can never fire.",
        parameters_model=ReductionParameters,
        result_model=ReductionResult,
        compute=remove_dead_transitions,
        preserves=DEAD_PRESERVES,
    ),
    OperationDefinition(
        name="remove-self-loop-transitions",
        kind="reduction",
        summary="Remove the transitions that consume exactly what they produce.",
        parameters_model=ReductionParameters,
        result_model=ReductionResult,
        compute=remove_self_loop_transitions,
        preserves=SELF_LOOP_PRESERVES,
    ),
)
