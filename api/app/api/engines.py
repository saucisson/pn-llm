"""Routes about engines."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.domain.contract import Envelope
from app.domain.models import EngineInfo

from .deps import EnginesDep
from .envelopes import wrap

router = APIRouter(prefix="/v1", tags=["engines"])


@router.get("/engines")
def get_engines(*, engines: EnginesDep) -> Envelope[tuple[EngineInfo, ...]]:
    """List the registered engines and whether they are available here."""
    started = time.perf_counter()
    listed = engines.list_engines()
    return wrap(
        tool="engines.list",
        net_id=None,
        started=started,
        data=tuple(sorted(listed, key=lambda engine: engine.name)),
    )
