"""The analyses: one module each, listed here in the catalog."""

from __future__ import annotations

from app.domain.operations import NoParameters, OperationDefinition

from .conflict_sets import ConflictSetsParameters, ConflictSetsResult, conflict_sets
from .connected_components import (
    ConnectedComponentsParameters,
    ConnectedComponentsResult,
    connected_components,
)
from .dead_transitions import DeadTransitionsResult, dead_transitions
from .net_class import NetClassResult, net_class
from .p_invariants import PInvariantsParameters, PInvariantsResult, p_invariants
from .place_bounds import PlaceBoundsParameters, PlaceBoundsResult, place_bounds
from .siphons import (
    MinimalSiphonsParameters,
    MinimalTrapsParameters,
    SiphonsResult,
    TrapsResult,
    minimal_siphons,
    minimal_traps,
)
from .t_invariants import TInvariantsParameters, TInvariantsResult, t_invariants

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
    OperationDefinition(
        name="t-invariants",
        kind="analysis",
        summary="Minimal-support transition invariants: firing counts that return to the marking.",
        parameters_model=TInvariantsParameters,
        result_model=TInvariantsResult,
        compute=t_invariants,
    ),
    OperationDefinition(
        name="place-bounds",
        kind="analysis",
        summary="Bound of each place that the structure shows: finite, unbounded or unknown.",
        parameters_model=PlaceBoundsParameters,
        result_model=PlaceBoundsResult,
        compute=place_bounds,
    ),
    OperationDefinition(
        name="minimal-siphons",
        kind="analysis",
        summary="Minimal siphons: place sets that, once empty, stay empty.",
        parameters_model=MinimalSiphonsParameters,
        result_model=SiphonsResult,
        compute=minimal_siphons,
    ),
    OperationDefinition(
        name="minimal-traps",
        kind="analysis",
        summary="Minimal traps: place sets that, once marked, stay marked.",
        parameters_model=MinimalTrapsParameters,
        result_model=TrapsResult,
        compute=minimal_traps,
    ),
    OperationDefinition(
        name="dead-transitions",
        kind="analysis",
        summary="Transitions that can never fire, from the structure and the initial marking.",
        parameters_model=NoParameters,
        result_model=DeadTransitionsResult,
        compute=dead_transitions,
    ),
    OperationDefinition(
        name="conflict-sets",
        kind="analysis",
        summary="Groups of transitions that compete for the same input places.",
        parameters_model=ConflictSetsParameters,
        result_model=ConflictSetsResult,
        compute=conflict_sets,
    ),
    OperationDefinition(
        name="connected-components",
        kind="analysis",
        summary="Parts of the net not linked by any arc, largest first.",
        parameters_model=ConnectedComponentsParameters,
        result_model=ConnectedComponentsResult,
        compute=connected_components,
    ),
)
OPERATIONS: tuple[OperationDefinition, ...] = ANALYSES


def find_operation(*, name: str) -> OperationDefinition | None:
    """Return the operation of that name, or None."""
    return next((op for op in OPERATIONS if op.name == name), None)
