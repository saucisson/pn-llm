"""Routes about checks and jobs."""

from __future__ import annotations

import time
from http import HTTPStatus

from fastapi import APIRouter, Response

from app.application.traces import TraceView
from app.domain.contract import Envelope
from app.domain.engine_contract import Trace
from app.domain.models import CheckRequest, Job

from .deps import ChecksDep, TracesDep
from .envelopes import wrap

router = APIRouter(prefix="/v1", tags=["checks"])


@router.post("/nets/{net_id}/checks", status_code=HTTPStatus.ACCEPTED)
def start_check(
    *, net_id: str, body: CheckRequest, checks: ChecksDep, response: Response
) -> Envelope[Job]:
    """Queue (or reuse) an asynchronous check of formulas on a net; a worker runs it."""
    started = time.perf_counter()
    submission = checks.submit(net_id=net_id, request=body)
    response.headers["Location"] = f"/v1/jobs/{submission.job.job_id}"
    return wrap(tool="check.submit", net_id=net_id, started=started, data=submission.job)


@router.get("/jobs/{job_id}")
def get_job(*, job_id: str, checks: ChecksDep) -> Envelope[Job]:
    """Return a job with its state and results."""
    started = time.perf_counter()
    job = checks.get(job_id=job_id)
    return wrap(tool="check.get", net_id=job.net_id, started=started, data=job)


@router.get("/jobs/{job_id}/results/{result_index}/trace")
def get_trace(
    *, job_id: str, result_index: int, traces: TracesDep, net: TraceView = "original"
) -> Envelope[Trace]:
    """Return the counterexample of one result: the transitions fired.

    For a check run on a reduced net the trace is lifted to the original net unless
    ``?net=reduced`` asks for the net it was found on.
    """
    started = time.perf_counter()
    trace = traces.get(job_id=job_id, result_index=result_index, view=net)
    return wrap(tool="check.trace", net_id=trace.net_id, started=started, data=trace)


@router.post("/jobs/{job_id}/retry", status_code=HTTPStatus.ACCEPTED)
def retry_job(*, job_id: str, checks: ChecksDep) -> Envelope[Job]:
    """Queue an interrupted job again."""
    started = time.perf_counter()
    job = checks.retry(job_id=job_id)
    return wrap(tool="check.retry", net_id=job.net_id, started=started, data=job)


@router.delete("/jobs/{job_id}", status_code=HTTPStatus.NO_CONTENT)
def cancel_job(*, job_id: str, checks: ChecksDep) -> Response:
    """Cancel a job that has not finished."""
    checks.cancel(job_id=job_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)
