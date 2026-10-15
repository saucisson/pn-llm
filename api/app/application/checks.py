"""Use cases about checks (verification jobs)."""

from __future__ import annotations

import uuid

from app.domain.engine_check import all_error, interpret_report
from app.domain.engine_contract import EngineRequest, Trace
from app.domain.errors import InvalidFormulaError, InvalidRequestError, NotFoundError
from app.domain.formula_check import check_formula
from app.domain.models import (
    CheckRequest,
    Job,
    JobState,
    JobSubmission,
)
from app.domain.net_structure import build_structure
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

        A new job is queued: a worker runs it (``run_next``).

        Raises:
            NotFoundError: if the net is unknown.
            InvalidRequestError: if the requested engine is not registered.
            InvalidFormulaError: if a formula cites unknown ids or misuses its logic.
        """
        stored = self._nets.load_net(net_id=net_id)  # raises NotFoundError
        structure = build_structure(document=stored.document, net_id=net_id)
        for index, formula in enumerate(request.formulas):
            report = check_formula(formula=formula, structure=structure)
            if not report.valid:
                first = report.errors[0]
                raise InvalidFormulaError(
                    f"Formula {formula.id!r}: {first.message}",
                    location=f"/formulas/{index}{first.path}",
                )
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
        return self._jobs.create_or_get_job(job=job)

    def run_next(self) -> bool:
        """Claim the oldest queued job and run it to completion; False if the queue was empty.

        An engine crash never leaves the job running: it becomes an ERROR verdict per formula.
        Safe to call from several workers and several processes: a job is claimed by exactly one.
        """
        claimed = self._jobs.claim_next_job(lease_seconds=self._lease_seconds)
        if claimed is None:
            return False
        job = claimed
        job_id = job.job_id
        net = self._nets.load_net(net_id=job.net_id)
        structure = build_structure(document=net.document, net_id=job.net_id)
        engine = self._engines.choose(requested=job.request.engine)
        try:
            with LeaseKeeper(
                renew=lambda: self._jobs.renew_lease(
                    job_id=job_id, lease_seconds=self._lease_seconds
                ),
                lease_seconds=self._lease_seconds,
                on_lost=lambda: self._engines.stop(job_id=job_id),
            ):
                report = self._engines.run(
                    engine=engine,
                    pnml=render_pnml(document=net.document),
                    request=EngineRequest(
                        net_id=job.net_id,
                        formulas=job.request.formulas,
                        limits=job.request.limits,
                    ),
                    job_id=job_id,
                )
            outcome = interpret_report(
                report=report,
                request=job.request,
                engine=engine,
                net_id=job.net_id,
                structure=structure,
            )
        except Exception as exc:  # noqa: BLE001  (adapter bugs are reported, not propagated)
            outcome = all_error(
                request=job.request,
                engine=engine,
                warning=f"runner_exception: {type(exc).__name__}",
            )
        # A counterexample is served at a stable address, built from the position of its result.
        results = tuple(
            result.model_copy(
                update={
                    "trace_url": (
                        f"/v1/jobs/{job_id}/results/{index}/trace"
                        if any(trace.formula_id == result.id for trace in outcome.traces)
                        else None
                    )
                }
            )
            for index, result in enumerate(outcome.results)
        )
        self._jobs.finish(job_id=job_id, results=results, traces=outcome.traces)
        return True

    def drain(self) -> int:
        """Run queued jobs, one after the other, until the queue is empty; return how many ran."""
        count = 0
        while self.run_next():
            count += 1
        return count

    def retry(self, *, job_id: str) -> Job:
        """Queue an interrupted job again (its engine run was lost) and return it.

        Raises:
            NotFoundError: if the job is unknown.
            InvalidRequestError: if the job is not interrupted.
            ConflictError: if an equivalent job is already live.
        """
        job = self._jobs.load_job(job_id=job_id)  # raises NotFoundError
        if not self._jobs.requeue(job_id=job_id):
            raise InvalidRequestError(
                f"Only an interrupted job can be retried: {job_id} is {job.state}"
            )
        return self._jobs.load_job(job_id=job_id)

    def recover_interrupted(self) -> int:
        """Mark jobs whose owner stopped renewing their lease as interrupted; return the count.

        Safe to call from any process at any time.
        """
        return self._jobs.recover_interrupted()

    def purge_old_jobs(self, *, retention_s: float) -> int:
        """Delete finished jobs older than the retention period; return how many."""
        return self._jobs.purge_finished_jobs(older_than_s=retention_s)

    def get(self, *, job_id: str) -> Job:
        """Return a job.

        Raises:
            NotFoundError: if the job is unknown.
        """
        return self._jobs.load_job(job_id=job_id)

    def trace(self, *, job_id: str, result_index: int) -> Trace:
        """Return the counterexample of the ``result_index``-th result of a job.

        Raises:
            NotFoundError: if the job, the result or its trace does not exist.
        """
        job = self._jobs.load_job(job_id=job_id)
        if not 0 <= result_index < len(job.results):
            raise NotFoundError(f"Job {job_id} has no result {result_index}")
        return self._jobs.load_trace(job_id=job_id, formula_id=job.results[result_index].id)

    def cancel(self, *, job_id: str) -> None:
        """Cancel a job that has not finished; finished jobs are left untouched.

        Raises:
            NotFoundError: if the job is unknown.
        """
        self._jobs.load_job(job_id=job_id)  # raises NotFoundError
        self._jobs.cancel(job_id=job_id)
        self._engines.stop(job_id=job_id)  # free the CPU now, not at the next lease renewal
