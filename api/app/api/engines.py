"""Routes about engines."""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.models import EngineInfo

from .deps import EnginesDep

router = APIRouter(prefix="/v1", tags=["engines"])


@router.get("/engines", response_model=tuple[EngineInfo, ...])
def get_engines(*, engines: EnginesDep) -> tuple[EngineInfo, ...]:
    """List the registered engines and whether they are available here."""
    return engines.list_engines()
