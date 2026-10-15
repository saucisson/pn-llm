"""Use cases about checks (verification jobs)."""

from __future__ import annotations

import uuid

from app.domain.errors import InvalidRequestError
from app.domain.models import (
    CheckRequest,
    FormulaResult,
    Job,
    JobState,
    JobSubmission,
    Verdict,
)
from app.domain.pnml_export import render_pnml

from .leases import LeaseKeeper
from .ports import EngineGateway, JobRepository, NetRepository

JOB_ID_LENGTH = 12


class CheckService:
    """Submit, run, read and cancel checks."""

    def __init__(
        self,
        *,
        nets: NetRepository,
        jobs: JobRepository,
        engines: EngineGateway,
        lease_seconds: float,
    ) -> None:
        """Create the service with the ports it needs and the job lease duration."""
        self._nets = nets
        self._jobs = jobs
        self._engines = engines
        self._lease_seconds = lease_seconds

    def submit(self, *, net_id: str, request: CheckRequest) -> JobSubmission:
        """Register a check. The same net and request give the same job, also across restarts.

        The caller executes the job only when ``created`` is True.

        Raises:
            NotFoundError: if the net is unknown.
            InvalidRequestError: if the requested engine is not registered.
        """
        self._nets.load_net(net_id=net_id)  # raises NotFoundError
        # A job orphaned by a crashed process would otherwise block its own resubmission.
        self._jobs.recover_interrupted()
        if request.engine != "auto" and not self._engines.is_known(name=request.engine):
            raise InvalidRequestError(f"Unknown engine: {request.engine}")
        job = Job(
            job_id=uuid.uuid4().hex[:JOB_ID_LENGTH],
            net_id=net_id,
            state=JobState.QUEUED,
            request=request,
        )
        return self._jobs.create_or_get_job(job=job, lease_seconds=self._lease_seconds)

    def execute(self, *, job_id: str) -> None:
        """Run a queued job to completion. Does nothing if it is no longer queued.

        An engine crash never leaves the job running: it becomes an ERROR verdict per formula.
        """
        if not self._jobs.mark_running(job_id=job_id, lease_seconds=self._lease_seconds):
            return  # cancelled before it started, or claimed by another process
        job = self._jobs.load_job(job_id=job_id)
        net = self._nets.load_net(net_id=job.net_id)
        engine = self._engines.choose(requested=job.request.engine)
        try:
            with LeaseKeeper(jobs=self._jobs, job_id=job_id, lease_seconds=self._lease_seconds):
                results = self._engines.run(
                    engine=engine, pnml=render_pnml(document=net.document), request=job.request
                )
        except Exception as exc:  # noqa: BLE001  (adapter bugs are reported, not propagated)
            results = tuple(
                FormulaResult(
                    id=formula.id,
                    verdict=Verdict.ERROR,
                    engine=engine,
                    warnings=(f"runner_exception: {type(exc).__name__}",),
                )
                for formula in job.request.formulas
            )
        self._jobs.finish(job_id=job_id, results=results)

    def recover_interrupted(self) -> int:
        """Mark jobs whose owner stopped renewing their lease as interrupted; return the count.

        Safe to call from any process at any time.
        """
        return self._jobs.recover_interrupted()

    def get(self, *, job_id: str) -> Job:
        """Return a job.

        Raises:
            NotFoundError: if the job is unknown.
        """
        return self._jobs.load_job(job_id=job_id)

    def cancel(self, *, job_id: str) -> None:
        """Cancel a job that has not finished; finished jobs are left untouched.

        Raises:
            NotFoundError: if the job is unknown.
        """
        self._jobs.load_job(job_id=job_id)  # raises NotFoundError
        self._jobs.cancel(job_id=job_id)
