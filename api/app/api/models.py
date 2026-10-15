"""Routes about the contest models stored on the platform."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.domain.contract import Envelope
from app.domain.mcc import MccFamily, MccNetType, ModelEntry
from app.domain.mcc_properties import Examination, MccProperties
from app.domain.mcc_results import ResultSetInfo, RunStatistics
from app.domain.splits import Split

from .deps import ModelsDep, ResultsDep, SplitsDep
from .envelopes import wrap
from .inspection import PageDep

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models/families")
def get_model_families(*, models: ModelsDep) -> Envelope[tuple[MccFamily, ...]]:
    """List the contest families stored here, with their description, type and size."""
    started = time.perf_counter()
    return wrap(tool="models.families", net_id=None, started=started, data=models.families())


@router.get("/models")
def get_models(
    *,
    models: ModelsDep,
    page: PageDep,
    family: str | None = None,
    net_type: MccNetType | None = None,
) -> Envelope[tuple[ModelEntry, ...]]:
    """List the stored contest nets (net id, family, instance), filtered by family and type."""
    started = time.perf_counter()
    found = models.entries(family=family, net_type=net_type, page=page)
    return wrap(tool="models.list", net_id=None, started=started, data=found.items, page=found.page)


@router.get("/models/{net_id}/properties/{examination}")
def get_model_properties(
    *, net_id: str, examination: Examination, models: ModelsDep
) -> Envelope[MccProperties]:
    """Return the properties the contest asks about a net for one examination (origin mcc)."""
    started = time.perf_counter()
    return wrap(
        tool="models.properties",
        net_id=net_id,
        started=started,
        data=models.properties(net_id=net_id, examination=examination),
    )


@router.get("/models/results/summary")
def get_result_summary(
    *,
    results: ResultsDep,
    page: PageDep,
    tool: str | None = None,
    examination: str | None = None,
    family: str | None = None,
) -> Envelope[tuple[RunStatistics, ...]]:
    """Success rate and median time of each tool per examination and family, from the contest."""
    started = time.perf_counter()
    found = results.statistics(tool=tool, examination=examination, family=family, page=page)
    return wrap(
        tool="models.results.summary",
        net_id=None,
        started=started,
        data=found.items,
        page=found.page,
    )


@router.get("/models/results/sets")
def get_result_sets(*, results: ResultsDep) -> Envelope[tuple[ResultSetInfo, ...]]:
    """List the stored sets of published results with their provenance (URL, year, hash)."""
    started = time.perf_counter()
    return wrap(
        tool="models.results.sets", net_id=None, started=started, data=results.result_sets()
    )


@router.get("/models/splits")
def get_split_names(*, splits: SplitsDep) -> Envelope[tuple[str, ...]]:
    """List the names of the frozen splits of the families."""
    started = time.perf_counter()
    return wrap(tool="models.splits.list", net_id=None, started=started, data=splits.names())


@router.get("/models/splits/{name}")
def get_split(*, name: str, splits: SplitsDep) -> Envelope[Split]:
    """Return a frozen split: each family's role (dev fold or held-out test)."""
    started = time.perf_counter()
    return wrap(tool="models.splits.get", net_id=None, started=started, data=splits.get(name=name))
