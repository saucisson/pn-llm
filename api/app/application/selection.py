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

from app.domain.capabilities import examinations_needed, property_class_of
from app.domain.errors import InvalidRequestError
from app.domain.formula import Formula
from app.domain.models import DomainModel, EngineInfo, Limits
from app.domain.predictor import Predictor, expected_time_s, features_of, probability_of

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
    basis: Literal["predictor", "history", "preference"]
    ranked: tuple[RankedEngine, ...]


class Forecast(DomainModel):
    """What the model expects of an engine on a net: the chance of an answer, and how long."""

    chance: float
    seconds: float | None


class Scored(DomainModel):
    """A candidate engine and what the contest history says of it."""

    info: EngineInfo
    runs: int
    probability: float | None
    seconds: float | None


class SelectionService:
    """Rank the engines that can check some properties on a net."""

    def __init__(
        self,
        *,
        nets: NetRepository,
        engines: EngineGateway,
        results: ResultsRepository,
        predictor: Predictor | None = None,
    ) -> None:
        """Create the service over the nets, the engines, the results and maybe a model."""
        self._nets = nets
        self._engines = engines
        self._results = results
        self._predictor = predictor

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
        summary = stored.summary
        features = features_of(
            places=summary.places,
            transitions=summary.transitions,
            arcs=summary.arcs,
            colored=colored,
        )
        needed = sorted(
            {
                alternative[0]
                for c in classes
                for alternative in examinations_needed(property_class=c)
            }
        )
        chances = self.forecasts(
            features=features, examinations=needed, tools=[item.info.name for item in scored]
        )
        if chances:
            return Selection(
                property_classes=keys,
                basis="predictor",
                ranked=tuple(
                    RankedEngine(
                        engine=item.info.name,
                        version=item.info.version,
                        success_probability=chances[item.info.name].chance,
                        expected_time_s=chances[item.info.name].seconds,
                        rationale=(
                            f"the model gives it {chances[item.info.name].chance:.0%} to answer on "
                            f"{summary.places} places and {summary.transitions} transitions"
                        ),
                    )
                    for item in sorted(
                        (i for i in scored if i.info.name in chances),
                        key=lambda i: (
                            -self.rank_score(
                                tool=i.info.name, chances=chances, examinations=needed
                            ),
                            i.info.name,
                        ),
                    )
                ),
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

    def forecasts(
        self, *, features: tuple[float, ...], examinations: list[str], tools: list[str]
    ) -> dict[str, Forecast]:
        """Return, per engine the model covers for every examination needed, its mean forecast."""
        if self._predictor is None:
            return {}
        chances: dict[str, list[float]] = {}
        times: dict[str, list[float]] = {}
        for tree in self._predictor.trees:
            if tree.examination in examinations and tree.tool in tools:
                chances.setdefault(tree.tool, []).append(
                    probability_of(tree=tree.tree, features=features)
                )
                seconds = expected_time_s(tree=tree.tree, features=features)
                if seconds is not None:
                    times.setdefault(tree.tool, []).append(seconds)
        return {
            tool: Forecast(
                chance=sum(values) / len(values),
                seconds=sum(times[tool]) / len(times[tool]) if tool in times else None,
            )
            for tool, values in chances.items()
            if len(values) == len(examinations)
        }

    def rank_score(
        self, *, tool: str, chances: dict[str, Forecast], examinations: list[str]
    ) -> float:
        """Rank by the chance, plus the model's margin for the default engine of the question."""
        if self._predictor is None:
            return chances[tool].chance
        defaults = {d.tool for d in self._predictor.defaults if d.examination in examinations}
        return chances[tool].chance + (self._predictor.margin if tool in defaults else 0.0)
