"""Routes about checks and jobs."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from app.domain.models import CheckRequest, Job

from .deps import ChecksDep

router = APIRouter(prefix="/v1", tags=["checks"])


@router.post("/nets/{net_id}/checks", response_model=Job, status_code=HTTPStatus.ACCEPTED)
def start_check(*, net_id: str, body: CheckRequest, checks: ChecksDep) -> JSONResponse:
    """Start (or reuse) an asynchronous check of formulas on a net."""
    submission = checks.submit(net_id=net_id, request=body)
    # Only a new job is executed; an equivalent live job is already on its way.
    background = (
        BackgroundTask(checks.execute, job_id=submission.job.job_id) if submission.created else None
    )
    return JSONResponse(
        status_code=HTTPStatus.ACCEPTED,
        content=submission.job.model_dump(mode="json"),
        background=background,
    )


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(*, job_id: str, checks: ChecksDep) -> Job:
    """Return a job with its state and results."""
    return checks.get(job_id=job_id)


@router.delete("/jobs/{job_id}", status_code=HTTPStatus.NO_CONTENT)
def cancel_job(*, job_id: str, checks: ChecksDep) -> Response:
    """Cancel a job that has not finished."""
    checks.cancel(job_id=job_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)
