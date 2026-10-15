"""Routes about nets."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app.domain.errors import NotAcceptableError, UnsupportedMediaTypeError
from app.domain.nets import NetFormat, NetRegistration

from .deps import NetsDep
from .negotiation import JSON, PNML, PNML_REQUEST_TYPES, media_type_of, negotiate

router = APIRouter(prefix="/v1/nets", tags=["nets"])

# Nets never change, so any cache may keep a representation for as long as it likes.
IMMUTABLE = "public, max-age=31536000, immutable"


@router.post("", response_model=NetRegistration)
async def upload_net(*, request: Request, response: Response, nets: NetsDep) -> NetRegistration:
    """Register a net: a JSON net document (default) or PNML. The id is the hash of the document."""
    media_type = media_type_of(content_type=request.headers.get("content-type")) or JSON
    if media_type == JSON:
        net_format = NetFormat.JSON
    elif media_type in PNML_REQUEST_TYPES:
        net_format = NetFormat.PNML
    else:
        raise UnsupportedMediaTypeError(
            f"Unsupported Content-Type {media_type!r}: use {JSON} or {PNML}"
        )
    payload = await request.body()
    saved = await run_in_threadpool(nets.register, payload=payload, format=net_format)
    net_id = saved.stored.summary.net_id
    response.status_code = HTTPStatus.CREATED if saved.created else HTTPStatus.OK
    response.headers["Location"] = f"/v1/nets/{net_id}"
    return NetRegistration(net_id=net_id, created=saved.created, summary=saved.stored.summary)


@router.get("/{net_id}")
def get_net(*, request: Request, net_id: str, nets: NetsDep) -> Response:
    """Return the net: its JSON document (default) or canonical PNML with ``Accept``."""
    chosen = negotiate(accept=request.headers.get("accept"), offered=(JSON, PNML))
    if chosen is None:
        raise NotAcceptableError(f"Cannot produce the requested type: offered {JSON}, {PNML}")
    headers = {"ETag": f'"{net_id}"', "Cache-Control": IMMUTABLE, "Vary": "Accept"}
    if chosen == PNML:
        return Response(content=nets.pnml(net_id=net_id), media_type=PNML, headers=headers)
    document = nets.get(net_id=net_id).document.sorted_by_id()
    return Response(
        content=document.model_dump_json(exclude_none=True, exclude_defaults=True),
        media_type=JSON,
        headers=headers,
    )
