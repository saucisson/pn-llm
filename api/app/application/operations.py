"""Use cases about operations: describe them, submit them, run them and read their results.

Every operation runs the same way (ADR 0014): a run is queued, claimed by a worker, executed by an
engine that declares the operation, checked, and stored. A finished run is the cache of its key
(net, operation, parameters, engine and tool version), so asking again is free.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from app.domain.analyses import OPERATIONS, find_operation
from app.domain.contract import ErrorInfo, ToolInfo
from app.domain.engine_contract import EngineRequest
from app.domain.errors import InvalidRequestError, NotFoundError
from app.domain.models import DomainModel
from app.domain.net_structure import build_structure
from app.domain.operation_check import interpret_operation_report
from app.domain.operations import (
    OperationDefinition,
    OperationDescription,
    OperationOutcome,
    OperationRequest,
    OperationRun,
    RunState,
    RunSubmission,
)
from app.domain.pnml_export import render_pnml

from .leases import LeaseKeeper
from .ports import EngineGateway, NetRepository, OperationRepository

RUN_ID_LENGTH = 12
POLL_SECONDS = 0.05
FINISHED = frozenset({RunState.DONE, RunState.FAILED})

logger = logging.getLogger("pnverif.operations")


class OperationService:
    """Describe, submit, run and read operations on nets."""

    def __init__(
        self,
        *,
        nets: NetRepository,
        runs: OperationRepository,
        engines: EngineGateway,
        lease_seconds: float,
        wait_seconds: float,
    ) -> None:
        """Create the service with its ports, the run lease and how long a request waits."""
        self._nets = nets
        self._runs = runs
        self._engines = engines
        self._lease_seconds = lease_seconds
        self.wait_seconds = wait_seconds

    def catalog(self) -> tuple[OperationDescription, ...]:
        """Describe every operation: route, parameters, result and the engines that perform it."""
        engines = self._engines.list_engines()
        return tuple(
            OperationDescription(
                name=op.name,
                kind=op.kind,
                summary=op.summary,
                route=op.route,
                parameters_schema=op.parameters_model.model_json_schema(),
                result_schema=op.result_model.model_json_schema(),
                supports_colored=op.supports_colored,
                preserves=op.preserves,
                engines=tuple(e.name for e in engines if op.name in e.operations and e.available),
            )
            for op in OPERATIONS
        )

    def submit(
        self, *, net_id: str, operation: str, request: OperationRequest[DomainModel]
    ) -> RunSubmission:
        """Queue an operation on a net; the same request gives the same run, finished or not.

        Raises:
            NotFoundError: if the net or the operation is unknown.
            InvalidRequestError: if the net is of a kind the operation does not handle, or no
                engine can perform it.
        """
        stored = self._nets.load_net(net_id=net_id)
        definition = find_operation(name=operation)
        if definition is None:
            raise NotFoundError(f"Unknown operation: {operation}")
        structure = build_structure(document=stored.document, net_id=net_id)
        if structure.kind != "pt" and not definition.supports_colored:
            raise InvalidRequestError(f"{operation} is not available on colored nets yet")
        self._runs.recover_interrupted_runs()
        engine = self._engines.choose_for(operation=operation, requested=request.engine)
        version = self._engines.version_of(engine=engine)
        parameters = request.parameters.model_dump(mode="json")
        key = hashlib.sha256(
            json.dumps([net_id, operation, parameters, engine, version], sort_keys=True).encode()
        ).hexdigest()
        run = OperationRun(
            run_id=uuid.uuid4().hex[:RUN_ID_LENGTH],
            net_id=net_id,
            operation=operation,
            engine=engine,
            tool_version=version,
            parameters=parameters,
            limits=request.limits,
            state=RunState.QUEUED,
        )
        return self._runs.create_or_get_run(run=run, key=key)

    def wait(self, *, run_id: str, seconds: float) -> OperationRun:
        """Return the run once it has finished or after ``seconds``, whichever comes first."""
        deadline = time.monotonic() + seconds
        while True:
            run = self._runs.load_run(run_id=run_id)
            if run.state not in {RunState.QUEUED, RunState.RUNNING} or time.monotonic() >= deadline:
                return run
            time.sleep(POLL_SECONDS)

    def get(self, *, run_id: str) -> OperationRun:
        """Return a run, or raise NotFoundError."""
        return self._runs.load_run(run_id=run_id)

    def cancel(self, *, run_id: str) -> None:
        """Cancel a queued or running run; a finished one is left as it is."""
        self._runs.load_run(run_id=run_id)  # raises NotFoundError
        self._runs.cancel_run(run_id=run_id)
        self._engines.stop(job_id=run_id)

    def run_next(self) -> bool:
        """Claim the oldest queued run and run it to its end; False if the queue was empty.

        An engine crash never leaves the run running: it ends failed, with the reason.
        """
        run = self._runs.claim_next_run(lease_seconds=self._lease_seconds)
        if run is None:
            return False
        definition: OperationDefinition | None = find_operation(name=run.operation)
        began = time.monotonic()
        try:
            if definition is None:
                message = f"unknown operation {run.operation}"
                raise InvalidRequestError(message)
            net = self._nets.load_net(net_id=run.net_id)
            structure = build_structure(document=net.document, net_id=run.net_id)
            with LeaseKeeper(
                renew=lambda: self._runs.renew_lease(
                    run_id=run.run_id, lease_seconds=self._lease_seconds
                ),
                lease_seconds=self._lease_seconds,
                on_lost=lambda: self._engines.stop(job_id=run.run_id),
            ):
                report = self._engines.run_operation(
                    engine=run.engine,
                    pnml=render_pnml(document=net.document),
                    request=EngineRequest(
                        kind="analysis",
                        net_id=run.net_id,
                        operation=run.operation,
                        parameters=run.parameters,
                        limits=run.limits,
                    ),
                    job_id=run.run_id,
                )
            outcome = interpret_operation_report(
                report=report,
                definition=definition,
                engine=run.engine,
                engine_version=run.tool_version,
                structure=structure,
            )
        except Exception as exc:  # noqa: BLE001 - adapter and infrastructure bugs are reported
            outcome = OperationOutcome(
                status="failed",
                tool=ToolInfo(name=run.engine, version=run.tool_version),
                error=ErrorInfo(
                    code=f"runner_exception_{type(exc).__name__}", message=str(exc) or "no detail"
                ),
                elapsed_s=time.monotonic() - began,
            )
        self._runs.finish_run(run_id=run.run_id, outcome=outcome)
        logger.info(
            "run_finished",
            extra={"run_id": run.run_id, "operation": run.operation, "status": outcome.status},
        )
        return True

    def recover_interrupted(self) -> int:
        """Mark running runs whose owner stopped renewing their lease as interrupted."""
        return self._runs.recover_interrupted_runs()

    def purge_old_runs(self, *, retention_s: float) -> int:
        """Delete finished runs older than the retention period; return how many."""
        return self._runs.purge_finished_runs(older_than_s=retention_s)

    def drain(self) -> int:
        """Run queued runs until none is left (tests, and scripts without workers)."""
        count = 0
        while self.run_next():
            count += 1
        return count
