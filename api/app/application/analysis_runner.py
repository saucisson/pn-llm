"""Ask the platform for an analysis from inside a tool, and wait for it.

The agent works the queue itself while it waits, so it never depends on a free worker.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.domain.analysis_summary import Unavailable
from app.domain.errors import DomainError
from app.domain.models import DomainModel, Limits
from app.domain.operations import OperationRequest, OperationRun, RunState

from .operations import OperationService

GRACE_SECONDS = 30.0
UNFINISHED = frozenset({RunState.QUEUED, RunState.RUNNING})
ANALYSIS_TIMEOUT_S = 60


class AnalysisRunner:
    """Submit analyses to the operation service and wait for their results."""

    def __init__(self, *, operations: OperationService, poll_seconds: float) -> None:
        """Create the runner over the operation service."""
        self.operations = operations
        self._poll_seconds = poll_seconds

    def wait_for(
        self, *, run: OperationRun, timeout_s: int, is_cancelled: Callable[[], bool]
    ) -> OperationRun | None:
        """Work the queue until the run has finished; None if it was cancelled or timed out."""
        deadline = time.monotonic() + timeout_s + GRACE_SECONDS
        current = run
        while current.state in UNFINISHED:
            if is_cancelled() or time.monotonic() > deadline:
                self.operations.cancel(run_id=run.run_id)
                return None
            if not self.operations.run_next():
                time.sleep(self._poll_seconds)
            current = self.operations.get(run_id=run.run_id)
        return current

    def ask[R: DomainModel](
        self,
        *,
        net_id: str,
        name: str,
        parameters: DomainModel,
        result_type: type[R],
        is_cancelled: Callable[[], bool],
    ) -> R | Unavailable:
        """Run one analysis: its result, or why there is none."""
        limits = Limits(timeout_s=ANALYSIS_TIMEOUT_S)
        try:
            submission = self.operations.submit(
                net_id=net_id,
                operation=name,
                request=OperationRequest(limits=limits, parameters=parameters),
            )
        except DomainError as exc:
            return Unavailable(operation=name, reason=str(exc))
        run = self.wait_for(
            run=submission.run, timeout_s=limits.timeout_s, is_cancelled=is_cancelled
        )
        if run is None:
            return Unavailable(operation=name, reason="cancelled or timed out")
        if run.outcome is None or run.outcome.status != "ok":
            code = run.outcome.error.code if run.outcome and run.outcome.error else run.state.value
            return Unavailable(operation=name, reason=code)
        return result_type.model_validate(run.outcome.result)
