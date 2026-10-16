"""Routes about engines."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.application.selection import Selection, SelectionRequest
from app.domain.capabilities import CapabilityRow
from app.domain.contract import Envelope
from app.domain.equivalence import EquivalenceClass
from app.domain.models import EngineInfo

from .deps import EnginesDep, SelectionDep
from .envelopes import wrap

router = APIRouter(prefix="/v1", tags=["engines"])


@router.get("/engines")
def get_engines(
    *, engines: EnginesDep, can_check: str | None = None, colored: bool | None = None
) -> Envelope[tuple[EngineInfo, ...]]:
    """List the registered engines and whether they are available here.

    ``can_check`` keeps the engines that check a class of properties (such as
    ``ltl-fireability+next``); ``colored`` keeps those that do, or do not, read colored nets.
    """
    started = time.perf_counter()
    listed = engines.list_engines(can_check=can_check, colored=colored)
    return wrap(
        tool="engines.list",
        net_id=None,
        started=started,
        data=tuple(sorted(listed, key=lambda engine: engine.name)),
    )


@router.get("/engines/capabilities")
def get_capabilities(*, engines: EnginesDep) -> Envelope[tuple[CapabilityRow, ...]]:
    """For every class of properties, the engines that declare they can check it."""
    started = time.perf_counter()
    return wrap(
        tool="engines.capabilities", net_id=None, started=started, data=engines.capabilities()
    )


@router.get("/engines/equivalence")
def get_equivalence(*, engines: EnginesDep) -> Envelope[tuple[EquivalenceClass, ...]]:
    """For every class of properties, the engines interchangeable for it, with their caveats."""
    started = time.perf_counter()
    return wrap(
        tool="engines.equivalence", net_id=None, started=started, data=engines.equivalence()
    )


@router.post("/select-tools")
def select_tools(*, body: SelectionRequest, selection: SelectionDep) -> Envelope[Selection]:
    """Rank the engines that can check the formulas on the net, best first, with the evidence."""
    started = time.perf_counter()
    return wrap(
        tool="engines.select",
        net_id=body.net_id,
        started=started,
        data=selection.select(request=body),
    )
