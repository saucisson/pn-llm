"""Ports: what the use cases require from the outside world.

Defined here, implemented in ``app.infrastructure``. All parameters are keyword-only.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.descriptions import Description, DescriptionOrigin, SavedDescription
from app.domain.engine_contract import EngineReport, EngineRequest, Trace
from app.domain.models import (
    EngineInfo,
    FormulaResult,
    Job,
    JobSubmission,
)
from app.domain.net_document import NetDocument
from app.domain.nets import NetSummary, SavedNet, StoredNet


class NetRepository(Protocol):
    """Persistent storage of nets."""

    def save_net(self, *, summary: NetSummary, document: NetDocument) -> SavedNet:
        """Store a net if it is new; return what is stored (the existing net if already known)."""
        ...

    def load_net(self, *, net_id: str) -> StoredNet:
        """Return a stored net, or raise NotFoundError."""
        ...


class DescriptionRepository(Protocol):
    """Persistent storage of net descriptions."""

    def save_description(
        self, *, net_id: str, text: str, origin: DescriptionOrigin
    ) -> SavedDescription:
        """Store a description and link it to a net; adding the same text twice is a no-op."""
        ...

    def descriptions_of(self, *, net_id: str) -> tuple[Description, ...]:
        """Return the descriptions linked to a net, oldest first."""
        ...

    def load_description(self, *, description_id: str) -> tuple[Description, ...]:
        """Return a description with each of its links (one per net and origin).

        Raises:
            NotFoundError: if the description is unknown.
        """
        ...


class JobRepository(Protocol):
    """Persistent storage of jobs."""

    def create_or_get_job(self, *, job: Job) -> JobSubmission:
        """Insert ``job`` unless an equivalent live job exists (idempotency); say which was used.

        A queued job waits for a worker and has no lease; a running job has one (see below).
        """
        ...

    def claim_next_job(self, *, lease_seconds: float) -> Job | None:
        """Atomically claim the oldest queued job; None if the queue is empty."""
        ...

    def requeue(self, *, job_id: str) -> bool:
        """Queue an interrupted job again; False if it was not interrupted.

        Raises:
            ConflictError: if an equivalent live job exists.
        """
        ...

    def load_job(self, *, job_id: str) -> Job:
        """Return a job, or raise NotFoundError."""
        ...

    def renew_lease(self, *, job_id: str, lease_seconds: float) -> bool:
        """Extend a running job's lease; return False if it is no longer running."""
        ...

    def cancel(self, *, job_id: str) -> None:
        """Cancel a queued or running job; finished jobs are left untouched."""
        ...

    def finish(
        self, *, job_id: str, results: tuple[FormulaResult, ...], traces: tuple[Trace, ...]
    ) -> None:
        """Store results and counterexamples and mark the job done, only if it is still running."""
        ...

    def load_trace(self, *, job_id: str, formula_id: str) -> Trace:
        """Return the counterexample stored for a formula of a job, or raise NotFoundError."""
        ...

    def purge_finished_jobs(self, *, older_than_s: float) -> int:
        """Delete finished jobs and their traces older than ``older_than_s``; return the count."""
        ...

    def recover_interrupted(self) -> int:
        """Mark running jobs whose lease expired as interrupted; safe to call from any process."""
        ...


class EngineGateway(Protocol):
    """The verification engines."""

    def list_engines(self) -> tuple[EngineInfo, ...]:
        """Return every registered engine with its availability on this machine."""
        ...

    def is_known(self, *, name: str) -> bool:
        """Return True if ``name`` is a registered engine."""
        ...

    def choose(self, *, requested: str) -> str:
        """Return the engine to use for a request ("auto" lets the gateway decide)."""
        ...

    def run(self, *, engine: str, pnml: bytes, request: EngineRequest, job_id: str) -> EngineReport:
        """Run an engine on a net for a job; report what it produced (to be checked)."""
        ...

    def stop(self, *, job_id: str) -> None:
        """Kill the engine run of a job, if one is in progress (cancellation)."""
        ...
