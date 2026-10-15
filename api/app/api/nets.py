"""Routes about nets."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.domain.models import NetSummary

from .deps import NetsDep

router = APIRouter(prefix="/v1/nets", tags=["nets"])


@router.post("", response_model=NetSummary, status_code=HTTPStatus.CREATED)
async def upload_net(*, request: Request, nets: NetsDep) -> NetSummary:
    """Upload a PNML file (raw body, application/xml). The net_id is the hash of the content."""
    payload = await request.body()
    return await run_in_threadpool(nets.register, payload=payload)


@router.get("/{net_id}", response_model=NetSummary)
def get_net(*, net_id: str, nets: NetsDep) -> NetSummary:
    """Return the summary of a stored net."""
    return nets.get(net_id=net_id)
