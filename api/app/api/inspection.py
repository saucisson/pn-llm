"""Inspection routes: facts about a net, never the net itself (ADR 0013)."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.domain.colored_summary import ColoredSummary
from app.domain.contract import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    ElementRef,
    Envelope,
    Marking,
    Page,
    PageRequest,
)
from app.domain.inspection import (
    DEFAULT_NEIGHBOURHOOD_NODES,
    ArcView,
    ElementDetail,
    NameGroup,
    Neighbourhood,
    NetOverview,
)
from app.domain.pagination import encode_cursor
from app.domain.replay import ReplayRequest, ReplayResult

from .deps import InspectionDep
from .envelopes import wrap

router = APIRouter(prefix="/v1/nets/{net_id}", tags=["inspection"])


def get_page(
    *,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> PageRequest:
    """Read the pagination parameters of a list route."""
    return PageRequest(limit=limit, cursor=cursor)


PageDep = Annotated[PageRequest, Depends(get_page)]


@router.get("/summary")
def get_summary(*, net_id: str, inspection: InspectionDep) -> Envelope[NetOverview]:
    """Size, kind, size category and structural flags of the net: counts, no names."""
    started = time.perf_counter()
    return wrap(
        tool="net.summary",
        net_id=net_id,
        started=started,
        data=inspection.overview(net_id=net_id),
    )


@router.get("/colored")
def get_colored_summary(
    *, net_id: str, inspection: InspectionDep, examples: Annotated[int, Query(ge=0, le=20)] = 3
) -> Envelope[ColoredSummary]:
    """Summarize a colored net: sorts, groups of places and transitions, size of the unfolding."""
    started = time.perf_counter()
    summary = inspection.colored(net_id=net_id, examples=examples)
    return wrap(tool="inspect.colored", net_id=net_id, started=started, data=summary)


@router.get("/places")
def list_places(
    *,
    net_id: str,
    inspection: InspectionDep,
    page: PageDep,
    name: Annotated[str | None, Query(description="Glob on the name: * and ?")] = None,
    marked: Annotated[bool | None, Query(description="Hold tokens initially (P/T only)")] = None,
) -> Envelope[tuple[ElementRef, ...]]:
    """Places sorted by id, filtered by name pattern or initial marking."""
    started = time.perf_counter()
    found = inspection.places(net_id=net_id, name=name, marked=marked, page=page)
    return wrap(
        tool="net.places", net_id=net_id, started=started, data=found.items, page=found.page
    )


@router.get("/transitions")
def list_transitions(
    *,
    net_id: str,
    inspection: InspectionDep,
    page: PageDep,
    name: Annotated[str | None, Query(description="Glob on the name: * and ?")] = None,
) -> Envelope[tuple[ElementRef, ...]]:
    """Transitions sorted by id, filtered by name pattern."""
    started = time.perf_counter()
    found = inspection.transitions(net_id=net_id, name=name, page=page)
    return wrap(
        tool="net.transitions", net_id=net_id, started=started, data=found.items, page=found.page
    )


@router.get("/arcs")
def list_arcs(
    *,
    net_id: str,
    inspection: InspectionDep,
    page: PageDep,
    source: Annotated[str | None, Query(description="Id of the source element")] = None,
    target: Annotated[str | None, Query(description="Id of the target element")] = None,
) -> Envelope[tuple[ArcView, ...]]:
    """Arcs sorted by id, filtered by source or target element."""
    started = time.perf_counter()
    found = inspection.arcs(net_id=net_id, source=source, target=target, page=page)
    return wrap(tool="net.arcs", net_id=net_id, started=started, data=found.items, page=found.page)


@router.get("/search")
def search_elements(
    *,
    net_id: str,
    inspection: InspectionDep,
    page: PageDep,
    q: Annotated[str, Query(min_length=1, description="Text or glob, case-insensitive")],
) -> Envelope[tuple[ElementRef, ...]]:
    """Places and transitions whose name or id matches."""
    started = time.perf_counter()
    found = inspection.search(net_id=net_id, query=q, page=page)
    return wrap(
        tool="net.search", net_id=net_id, started=started, data=found.items, page=found.page
    )


@router.get("/marking")
def get_marking(*, net_id: str, inspection: InspectionDep, page: PageDep) -> Envelope[Marking]:
    """The places holding tokens initially (P/T nets)."""
    started = time.perf_counter()
    found = inspection.marking(net_id=net_id, page=page)
    return wrap(
        tool="net.marking",
        net_id=net_id,
        started=started,
        data=Marking(entries=found.items),
        page=found.page,
    )


@router.get("/neighbourhood")
def get_neighbourhood(
    *,
    net_id: str,
    inspection: InspectionDep,
    ids: Annotated[list[str], Query(description="Center element ids")],
    depth: Annotated[int, Query(description="Distance in arcs, 0 to 5")] = 1,
    max_elements: Annotated[int, Query(description="Size cap, 1 to 500")] = (
        DEFAULT_NEIGHBOURHOOD_NODES
    ),
) -> Envelope[Neighbourhood]:
    """Elements within a distance of some elements, capped, with an explicit cut marker."""
    started = time.perf_counter()
    found = inspection.neighbourhood(
        net_id=net_id, ids=tuple(ids), depth=depth, max_elements=max_elements
    )
    return wrap(tool="net.neighbourhood", net_id=net_id, started=started, data=found)


@router.post("/replay")
def replay_firings(
    *, net_id: str, body: ReplayRequest, inspection: InspectionDep
) -> Envelope[ReplayResult]:
    """Fire transitions in order on a P/T net; say where it fails and return the markings met."""
    started = time.perf_counter()
    result = inspection.replay(net_id=net_id, request=body)
    window = Page(
        returned=len(result.markings),
        total=result.markings_total,
        next_cursor=(
            encode_cursor(offset=result.markings_from + len(result.markings))
            if result.markings_from + len(result.markings) < result.markings_total
            else None
        ),
    )
    return wrap(tool="net.replay", net_id=net_id, started=started, data=result, page=window)


@router.get("/name-groups")
def get_name_groups(
    *,
    net_id: str,
    inspection: InspectionDep,
    page: PageDep,
    min_count: Annotated[int, Query(ge=2, description="Smallest family reported")] = 2,
) -> Envelope[tuple[NameGroup, ...]]:
    """Families of indexed names (``fork_1`` to ``fork_5``) as pattern, ranges and count."""
    started = time.perf_counter()
    found = inspection.name_groups(net_id=net_id, min_count=min_count, page=page)
    return wrap(
        tool="net.name_groups", net_id=net_id, started=started, data=found.items, page=found.page
    )


@router.get("/elements/{element_id:path}")
def get_element(
    *, net_id: str, element_id: str, inspection: InspectionDep
) -> Envelope[ElementDetail]:
    """One place or transition: name, tokens, and the arcs into and out of it."""
    started = time.perf_counter()
    return wrap(
        tool="net.element",
        net_id=net_id,
        started=started,
        data=inspection.element(net_id=net_id, element_id=element_id),
    )
