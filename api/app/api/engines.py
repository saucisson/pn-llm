"""Routes about engines."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app import __version__
from app.domain.contract import Envelope, ToolInfo
from app.domain.models import EngineInfo

from .deps import EnginesDep

router = APIRouter(prefix="/v1", tags=["engines"])


@router.get("/engines")
def get_engines(*, engines: EnginesDep) -> Envelope[tuple[EngineInfo, ...]]:
    """List the registered engines and whether they are available here."""
    started = time.perf_counter()
    listed = engines.list_engines()
    return Envelope[tuple[EngineInfo, ...]](
        tool=ToolInfo(name="engines.list", version=__version__),
        status="ok",
        data=tuple(sorted(listed, key=lambda engine: engine.name)),
        elapsed_s=time.perf_counter() - started,
    )
