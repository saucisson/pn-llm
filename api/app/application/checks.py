"""Use cases about checks (verification jobs)."""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app.domain.colored_formulas import translate_formula
from app.domain.engine_check import CheckOutcome, all_error, interpret_report
from app.domain.engine_contract import EngineRequest, Trace
from app.domain.errors import InvalidFormulaError, InvalidRequestError, NotFoundError
from app.domain.formula_check import check_formula
from app.domain.models import (
    CheckRequest,
    Job,
    JobState,
    JobSubmission,
)
from app.domain.net_structure import NetStructure, build_structure
from app.domain.pnml_export import render_pnml
from app.domain.portfolio import DEFINITIVE, EngineRun, merge_outcomes

from .leases import LeaseKeeper
from .ports import EngineGateway, JobRepository, NetRepository, OperationRepository
from .selection import SelectionRequest, SelectionService

JOB_ID_LENGTH = 12

logger = logging.getLogger("pnverif.jobs")


class CheckService:
    """Submit, run, read and cancel checks."""

    def __init__(
        self,
        *,
        nets: NetRepository,
        jobs: JobRepository,
        engines: EngineGateway,
        lease_seconds: float,
        selection: SelectionService | None = None,
        lineage: OperationRepository | None = None,
    ) -> None:
        """Create the service with its ports, the job lease and, to rank engines, a selector."""
        self._nets = nets
        self._jobs = jobs
        self._engines = engines
        self._lease_seconds = lease_seconds
        self._selection = selection
        self._lineage = lineage

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
        # On the unfolding of a colored net, a property may cite the colored elements.
        unfoldings = (
            ()
            if self._lineage is None
            else tuple(
                link for link in self._lineage.lineage_of(net_id=net_id) if link.rule == "unfold"
            )
        )
        if unfoldings:
            request = request.model_copy(
                update={
                    "formulas": tuple(
                        translate_formula(formula=f, lineage=unfoldings[0])
                        for f in request.formulas
                    )
                }
            )
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
        info = next((e for e in self._engines.list_engines() if e.name == request.engine), None)
        if structure.kind != "pt" and info is not None and not info.supports_colored:
            raise InvalidRequestError(
                f"{request.engine} does not check colored nets: unfold the net "
                "(POST /v1/nets/{id}/reductions/unfold) and check the unfolding"
            )
        job = Job(
            job_id=uuid.uuid4().hex[:JOB_ID_LENGTH],
            net_id=net_id,
            state=JobState.QUEUED,
            request=request,
        )
        return self._jobs.create_or_get_job(job=job)

    def plan(self, *, job: Job) -> tuple[str, ...]:
        """Choose the engines of a job: the one asked for, or the best ones for "auto".

        With a selector, "auto" means the ``portfolio`` best engines for the formulas on the net;
        without one, or when none qualifies, the placeholder choice of the gateway.
        """
        request = job.request
        if request.engine != "auto":
            return (request.engine,)
        if self._selection is not None:
            try:
                ranked = self._selection.select(
                    request=SelectionRequest(
                        net_id=job.net_id, formulas=request.formulas, limits=request.limits
                    )
                ).ranked
            except InvalidRequestError:
                ranked = ()
            if ranked:
                return tuple(item.engine for item in ranked[: request.portfolio])
        return (self._engines.choose(requested="auto"),)

    def run_on_engine(
        self,
        *,
        job: Job,
        engine: str,
        container_id: str,
        pnml: bytes,
        structure: NetStructure,
    ) -> CheckOutcome:
        """Run one engine on a job and check what it says; a crash is ERROR, never a verdict."""
        try:
            report = self._engines.run(
                engine=engine,
                pnml=pnml,
                request=EngineRequest(
                    net_id=job.net_id,
                    formulas=job.request.formulas,
                    limits=job.request.limits,
                    reduce=job.request.reduce,
                ),
                job_id=container_id,
            )
            return interpret_report(
                report=report,
                request=job.request,
                engine=engine,
                net_id=job.net_id,
                structure=structure,
            )
        except Exception as exc:  # noqa: BLE001  (adapter bugs are reported, not propagated)
            return all_error(
                request=job.request,
                engine=engine,
                warning=f"runner_exception: {type(exc).__name__}",
            )

    def run_portfolio(
        self,
        *,
        job: Job,
        engines: tuple[str, ...],
        pnml: bytes,
        structure: NetStructure,
    ) -> CheckOutcome:
        """Run several engines at the same time and merge what they say.

        Unless the request wants a cross-check, the engines still running are stopped as soon as
        every formula has a definitive verdict from some engine.
        """
        runs: list[EngineRun] = []
        with ThreadPoolExecutor(max_workers=len(engines)) as pool:
            futures = {
                pool.submit(
                    self.run_on_engine,
                    job=job,
                    engine=engine,
                    container_id=f"{job.job_id}.{engine}",
                    pnml=pnml,
                    structure=structure,
                ): engine
                for engine in engines
            }
            pending = set(futures)
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                runs.extend(EngineRun(engine=futures[f], outcome=f.result()) for f in done)
                merged = merge_outcomes(
                    formulas=job.request.formulas, runs=tuple(runs), structure=structure
                )
                settled = all(item.verdict in DEFINITIVE for item in merged.results)
                if pending and settled and not job.request.cross_check:
                    for future in pending:
                        self._engines.stop(job_id=f"{job.job_id}.{futures[future]}")
                    break
        return merge_outcomes(
            formulas=job.request.formulas,
            runs=tuple(sorted(runs, key=lambda run: engines.index(run.engine))),
            structure=structure,
        )

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
        began = time.monotonic()
        net = self._nets.load_net(net_id=job.net_id)
        structure = build_structure(document=net.document, net_id=job.net_id)
        engines = self.plan(job=job)
        engine = "+".join(engines)
        logger.info("job_started", extra={"job_id": job_id, "net_id": job.net_id, "engine": engine})
        pnml = render_pnml(document=net.document)
        with LeaseKeeper(
            renew=lambda: self._jobs.renew_lease(job_id=job_id, lease_seconds=self._lease_seconds),
            lease_seconds=self._lease_seconds,
            on_lost=lambda: self._engines.stop(job_id=job_id),
        ):
            if len(engines) == 1:
                outcome = self.run_on_engine(
                    job=job, engine=engines[0], container_id=job_id, pnml=pnml, structure=structure
                )
            else:
                outcome = self.run_portfolio(
                    job=job, engines=engines, pnml=pnml, structure=structure
                )
        # A property checked on the unfolding says so: the net the verdict is about is the colored
        # one, through the mapping.
        links = () if self._lineage is None else self._lineage.lineage_of(net_id=job.net_id)
        unfolding = next((link for link in links if link.rule == "unfold"), None)
        # A counterexample is served at a stable address, built from the position of its result.
        results = tuple(
            result.model_copy(
                update={
                    "warnings": (
                        result.warnings
                        if unfolding is None
                        else (*result.warnings, f"checked_on_unfolding:{unfolding.parent_id}")
                    ),
                    "trace_url": (
                        f"/v1/jobs/{job_id}/results/{index}/trace"
                        if any(trace.formula_id == result.id for trace in outcome.traces)
                        else None
                    ),
                }
            )
            for index, result in enumerate(outcome.results)
        )
        self._jobs.finish(job_id=job_id, results=results, traces=outcome.traces)
        logger.info(
            "job_finished",
            extra={
                "job_id": job_id,
                "net_id": job.net_id,
                "engine": engine,
                "duration_s": round(time.monotonic() - began, 3),
                "verdicts": [result.verdict.value for result in results],
            },
        )
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
