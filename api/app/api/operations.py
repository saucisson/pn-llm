"""Routes of the operations: the catalog, one route per analysis, and the runs (ADR 0014)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import JsonValue

from app.domain.catalog import OPERATIONS
from app.domain.contract import Envelope, ErrorInfo, ToolInfo
from app.domain.models import DomainModel
from app.domain.operations import (
    OperationDefinition,
    OperationDescription,
    OperationRequest,
    OperationRun,
    RunHandle,
    RunState,
)

from .deps import OperationsDep
from .envelopes import wrap

router = APIRouter(prefix="/v1", tags=["operations"])


class RunView(DomainModel):
    """The ``data`` of a run being followed: its state and, once finished, its result."""

    run_id: str
    operation: str
    state: RunState
    result: JsonValue = None
    # Why a failed run failed.
    error: ErrorInfo | None = None


def envelope_type(*, model: type[DomainModel]) -> type[Envelope[Any]]:
    """Return the envelope around a result model chosen at run time."""
    return Envelope[model]  # type: ignore[valid-type]  # the model is only known when routes are built


def envelope_of(
    *, run: OperationRun, definition: OperationDefinition, started: float
) -> Envelope[Any]:
    """Build the envelope of a finished run: its result, or the way it failed."""
    outcome = run.outcome
    if outcome is None:  # cancelled or interrupted before an engine answered
        return envelope_type(model=definition.result_model)(
            tool=ToolInfo(name=run.engine, version=run.tool_version),
            net_id=run.net_id,
            status="failed",
            error=ErrorInfo(code=run.state.value, message=f"The run was {run.state.value}"),
            elapsed_s=time.perf_counter() - started,
        )
    return envelope_type(model=definition.result_model)(
        tool=outcome.tool,
        net_id=run.net_id,
        status=outcome.status,
        data=None
        if outcome.result is None
        else definition.result_model.model_validate(outcome.result),
        warnings=outcome.warnings,
        error=outcome.error,
        elapsed_s=outcome.elapsed_s,
    )


@router.get("/operations")
def get_operations(*, operations: OperationsDep) -> Envelope[tuple[OperationDescription, ...]]:
    """List the analyses and reductions: route, parameters, result and the engines that run them."""
    started = time.perf_counter()
    return wrap(tool="operations.catalog", net_id=None, started=started, data=operations.catalog())


@router.get("/runs/{run_id}")
def get_run(*, run_id: str, operations: OperationsDep) -> Envelope[RunView]:
    """Follow the run of an operation: its state and, once it has finished, its result."""
    started = time.perf_counter()
    run = operations.get(run_id=run_id)
    return wrap(
        tool="operations.run",
        net_id=run.net_id,
        started=started,
        data=RunView(
            run_id=run.run_id,
            operation=run.operation,
            state=run.state,
            result=None if run.outcome is None else run.outcome.result,
            error=None if run.outcome is None else run.outcome.error,
        ),
    )


@router.delete("/runs/{run_id}", status_code=204)
def cancel_run(*, run_id: str, operations: OperationsDep) -> None:
    """Cancel a queued or running operation; a finished one keeps its result."""
    operations.cancel(run_id=run_id)


def add_operation_route(*, definition: OperationDefinition) -> None:
    """Register ``POST /v1/nets/{net_id}/<analyses|reductions>/<name>`` for one operation."""
    # The parameters model is only known when routes are built, so the body type is set below.
    request_model = OperationRequest[definition.parameters_model]  # type: ignore[name-defined]

    def endpoint(
        *, net_id: str, body: OperationRequest[DomainModel], operations: OperationsDep
    ) -> Envelope[Any] | JSONResponse:
        started = time.perf_counter()
        submission = operations.submit(net_id=net_id, operation=definition.name, request=body)
        run = operations.wait(run_id=submission.run.run_id, seconds=operations.wait_seconds)
        if run.state in {RunState.QUEUED, RunState.RUNNING}:
            handle = wrap(
                tool=f"operation.{definition.name}",
                net_id=net_id,
                started=started,
                data=RunHandle(
                    run_id=run.run_id, state=run.state, location=f"/v1/runs/{run.run_id}"
                ),
            )
            return JSONResponse(
                status_code=202,
                content=handle.model_dump(mode="json"),
                headers={"Location": f"/v1/runs/{run.run_id}"},
            )
        return envelope_of(run=run, definition=definition, started=started)

    kind = "analyses" if definition.kind == "analysis" else "reductions"
    endpoint.__annotations__["body"] = request_model
    router.add_api_route(
        definition.route.removeprefix("/v1"),
        endpoint,
        methods=["POST"],
        response_model=envelope_type(model=definition.result_model),
        summary=definition.summary,
        operation_id=f"{kind}.{definition.name}",
        responses={202: {"model": Envelope[RunHandle]}},
        tags=[kind],
    )


for _definition in OPERATIONS:
    add_operation_route(definition=_definition)
