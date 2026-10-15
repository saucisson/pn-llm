"""Use case: run the same cases on several engines and compare them with what is known."""

from __future__ import annotations

from app.domain.conformance import (
    ConformanceCase,
    ConformanceMatrix,
    MatrixCell,
    build_row,
    classify,
)
from app.domain.engine_contract import EngineRequest
from app.domain.models import Limits, Verdict

from .ports import EngineGateway


class ConformanceService:
    """Run conformance cases through the engine gateway, as a check would."""

    def __init__(self, *, engines: EngineGateway) -> None:
        """Create the service over the engine gateway."""
        self._engines = engines

    def available_engines(self) -> tuple[str, ...]:
        """Return the real engines whose image is present here, by name."""
        return tuple(
            sorted(
                engine.name
                for engine in self._engines.list_engines()
                if engine.available and engine.name != "dummy"
            )
        )

    def run(
        self, *, cases: tuple[ConformanceCase, ...], engines: tuple[str, ...], limits: Limits
    ) -> ConformanceMatrix:
        """Run every case on every engine; cases on the same net share one engine run.

        An engine that cannot run a case gives no answer for it (a verdict that is not TRUE or
        FALSE), never a wrong one.
        """
        by_net: dict[str, list[ConformanceCase]] = {}
        for case in cases:
            by_net.setdefault(case.net, []).append(case)
        cells: dict[tuple[str, str], MatrixCell] = {}
        for engine in engines:
            for net, group in by_net.items():
                request = EngineRequest(
                    net_id=net, formulas=tuple(case.formula for case in group), limits=limits
                )
                report = self._engines.run(
                    engine=engine, pnml=group[0].pnml, request=request, job_id=f"conf-{engine}"
                )
                answered = {item.result.id: item.result for item in report.results}
                for case in group:
                    result = answered.get(case.formula.id)
                    verdict = result.verdict if result is not None else Verdict.ERROR
                    cells[(engine, case.case_id)] = MatrixCell(
                        engine=engine,
                        verdict=verdict,
                        outcome=classify(expected=case.expected, verdict=verdict),
                        time_s=result.time_s if result is not None else 0.0,
                        warnings=result.warnings if result is not None else ("no_result",),
                    )
        return ConformanceMatrix(
            engines=engines,
            rows=tuple(
                build_row(
                    case=case,
                    cells=tuple(cells[(engine, case.case_id)] for engine in engines),
                )
                for case in cases
            ),
        )
