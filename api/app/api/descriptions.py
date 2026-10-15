"""Routes about net descriptions (ADR 0011)."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.domain.contract import Envelope
from app.domain.descriptions import Description, DescriptionOrigin, SavedDescription
from app.domain.errors import UnsupportedMediaTypeError

from .deps import DescriptionsDep
from .envelopes import wrap
from .negotiation import media_type_of

router = APIRouter(tags=["descriptions"])

TEXT_TYPES = frozenset({"text/plain", "text/markdown"})


@router.post("/v1/nets/{net_id}/descriptions")
async def add_description(
    *,
    net_id: str,
    request: Request,
    response: Response,
    descriptions: DescriptionsDep,
    origin: Annotated[DescriptionOrigin, Query()] = "user",
) -> Envelope[Description]:
    """Add a description (text/plain or text/markdown) to a net; the same text is a no-op."""
    started = time.perf_counter()
    media_type = media_type_of(content_type=request.headers.get("content-type"))
    if media_type not in TEXT_TYPES:
        raise UnsupportedMediaTypeError(
            f"Use Content-Type text/plain or text/markdown, not {media_type!r}"
        )
    payload = await request.body()
    saved: SavedDescription = await run_in_threadpool(
        descriptions.add, net_id=net_id, payload=payload, origin=origin
    )
    response.status_code = 201 if saved.created else 200
    response.headers["Location"] = f"/v1/descriptions/{saved.description.description_id}"
    return wrap(tool="description.add", net_id=net_id, started=started, data=saved.description)


@router.get("/v1/nets/{net_id}/descriptions")
def list_descriptions(
    *, net_id: str, descriptions: DescriptionsDep
) -> Envelope[tuple[Description, ...]]:
    """The descriptions of a net, oldest first."""
    started = time.perf_counter()
    return wrap(
        tool="description.list",
        net_id=net_id,
        started=started,
        data=descriptions.of_net(net_id=net_id),
    )


@router.get("/v1/descriptions/{description_id}")
def get_description(
    *, description_id: str, descriptions: DescriptionsDep
) -> Envelope[tuple[Description, ...]]:
    """A description with its links to nets (one entry per net and origin)."""
    started = time.perf_counter()
    return wrap(
        tool="description.get",
        net_id=None,
        started=started,
        data=descriptions.get(description_id=description_id),
    )
