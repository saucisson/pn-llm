"""Use case: which engines to ask, in which order, for some properties on a net.

Only engines that are available, take part in the examinations the properties need and read the
kind of net are candidates. They are ranked by how often and how fast they answered those
examinations in the contest results imported here; without such results, by a fixed preference.
The ranking never overrides a capability: an engine that cannot check a property is not listed.
"""

from __future__ import annotations

import statistics
from typing import Literal

from pydantic import Field

from app.domain.capabilities import property_class_of
from app.domain.errors import InvalidRequestError
from app.domain.formula import Formula
from app.domain.models import DomainModel, EngineInfo, Limits

from .ports import EngineGateway, NetRepository, ResultsRepository

PREFERENCE = ("itstools", "tapaal", "ty", "smpt")
INFINITE_S = 1e18


class SelectionRequest(DomainModel):
    """Body of ``POST /v1/select-tools``."""

    net_id: str
    formulas: tuple[Formula, ...] = Field(min_length=1)
    limits: Limits = Field(default_factory=Limits)


class RankedEngine(DomainModel):
    """An engine proposed for the properties, with the evidence for its rank."""

    engine: str
    version: str
    # From the contest history over the examinations the properties need; absent without history.
    success_probability: float | None = None
    expected_time_s: float | None = None
    rationale: str


class Selection(DomainModel):
    """The engines to ask, best first, and what the ranking rests on."""

    property_classes: tuple[str, ...]
    basis: Literal["history", "preference"]
    ranked: tuple[RankedEngine, ...]


class Scored(DomainModel):
    """A candidate engine and what the contest history says of it."""

    info: EngineInfo
    runs: int
    probability: float | None
    seconds: float | None


class SelectionService:
    """Rank the engines that can check some properties on a net."""

    def __init__(
        self, *, nets: NetRepository, engines: EngineGateway, results: ResultsRepository
    ) -> None:
        """Create the service over the stored nets, the engines and the imported results."""
        self._nets = nets
        self._engines = engines
        self._results = results

    def select(self, *, request: SelectionRequest) -> Selection:
        """Return the candidate engines for the formulas on the net, best first.

        Raises:
            NotFoundError: if the net is unknown.
            InvalidRequestError: if no available engine can check all the properties.
        """
        stored = self._nets.load_net(net_id=request.net_id)
        classes = {property_class_of(formula=f) for f in request.formulas}
        keys = tuple(sorted(c.key for c in classes))
        colored = stored.summary.kind != "pt"
        candidates = [
            info
            for info in self._engines.list_engines()
            if info.available
            and info.logics
            and info.name != "dummy"
            and set(keys) <= set(info.classes)
            and (info.supports_colored or not colored)
        ]
        if not candidates:
            raise InvalidRequestError(
                f"No available engine checks {', '.join(keys)}"
                + (" on a colored net" if colored else "")
            )
        examinations = sorted({e for info in candidates for e in info.examinations})
        rates = self._results.tool_rates(examinations=tuple(examinations))
        scored = []
        for info in candidates:
            mine = [r for r in rates if r.tool == info.name]
            runs = sum(r.runs for r in mine)
            times = [r.median_time_ms for r in mine if r.median_time_ms is not None]
            scored.append(
                Scored(
                    info=info,
                    runs=runs,
                    probability=sum(r.computed for r in mine) / runs if runs else None,
                    seconds=statistics.median(times) / 1000 if times else None,
                )
            )
        history = any(item.runs for item in scored)
        order = (
            sorted(scored, key=lambda item: (-(item.probability or 0), item.seconds or INFINITE_S))
            if history
            else sorted(
                scored,
                key=lambda item: (
                    PREFERENCE.index(item.info.name) if item.info.name in PREFERENCE else 99
                ),
            )
        )
        return Selection(
            property_classes=keys,
            basis="history" if history else "preference",
            ranked=tuple(
                RankedEngine(
                    engine=item.info.name,
                    version=item.info.version,
                    success_probability=item.probability,
                    expected_time_s=item.seconds,
                    rationale=(
                        f"answered {item.probability:.0%} of {item.runs} contest runs on the "
                        "same examinations"
                        if item.probability is not None
                        else "no contest history here; fixed order of preference"
                    ),
                )
                for item in order
            ),
        )
