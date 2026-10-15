"""Operations on a net: the analyses and the transformations, one endpoint each (ADR 0014).

An operation is defined once, here and in ``app.domain.analyses``: its name, its parameters, its
result and the function that computes it. The routes, the catalog and the engine that runs it are
all derived from that definition, so adding an operation changes no other file (ADR 0014, 6).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from .contract import ErrorInfo, ToolInfo
from .models import DomainModel, Limits
from .net_structure import NetStructure

OperationKind = Literal["analysis", "reduction"]


class NoParameters(DomainModel):
    """Parameters of an operation that has no option."""


class OperationRequest[P: DomainModel](DomainModel):
    """Body of every operation: which engine, within which limits, with which parameters."""

    engine: str = "auto"
    limits: Limits = Field(default_factory=Limits)
    parameters: P


class OperationDefinition(DomainModel):
    """What an operation is: the contract of its route and the function that computes it.

    ``compute`` is called with the structure of the net and the validated parameters and returns
    the result model; it is pure and deterministic, so its answer can be cached.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    kind: OperationKind
    summary: str
    parameters_model: type[DomainModel]
    result_model: type[DomainModel]
    compute: Callable[..., DomainModel]
    # Whether the operation is meaningful on a colored net as such (M3 extends the list).
    supports_colored: bool = False
    # For a reduction: the properties it preserves (docs/json-contract.md).
    preserves: tuple[str, ...] = ()

    @property
    def route(self) -> str:
        """The path of the operation, with the net id left as a parameter."""
        family = "analyses" if self.kind == "analysis" else "reductions"
        return f"/v1/nets/{{net_id}}/{family}/{self.name}"


class OperationDescription(DomainModel):
    """One entry of the catalog (``GET /v1/operations``)."""

    name: str
    kind: OperationKind
    summary: str
    route: str
    parameters_schema: JsonValue
    result_schema: JsonValue
    supports_colored: bool
    preserves: tuple[str, ...]
    engines: tuple[str, ...]


class RunState(StrEnum):
    """Lifecycle of the run of an operation, the same as a check's plus a failure."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class OperationOutcome(DomainModel):
    """What a run produced: the result as JSON of the operation's result model, or the error."""

    status: Literal["ok", "failed"]
    tool: ToolInfo
    result: JsonValue = None
    warnings: tuple[str, ...] = ()
    error: ErrorInfo | None = None
    elapsed_s: float = Field(default=0.0, ge=0)


class OperationRun(DomainModel):
    """One run of one operation on one net, queued, running or finished."""

    run_id: str
    net_id: str
    operation: str
    engine: str
    tool_version: str
    parameters: JsonValue
    limits: Limits
    state: RunState
    outcome: OperationOutcome | None = None


class RunSubmission(DomainModel):
    """Result of submitting an operation: the run to use and whether it is new."""

    run: OperationRun
    created: bool


class RunHandle(DomainModel):
    """The ``data`` of a ``202``: where to follow the run."""

    run_id: str
    state: RunState
    location: str


def compute_on(
    *, definition: OperationDefinition, structure: NetStructure, parameters: JsonValue
) -> DomainModel:
    """Validate ``parameters`` and run an operation's function on a net."""
    return definition.compute(
        structure=structure, parameters=definition.parameters_model.model_validate(parameters)
    )


class LineageExpansion(DomainModel):
    """A transition of a derived net and what its firing stands for in the parent."""

    transition: str
    original: tuple[str, ...]


class Lineage(DomainModel):
    """How a net was derived from another: the rule and what its transitions stand for there."""

    net_id: str
    parent_id: str
    rule: str
    expansions: tuple[LineageExpansion, ...] = ()
