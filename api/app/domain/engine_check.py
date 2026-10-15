"""Check what an engine reported and turn it into results of the platform.

An engine is a tool, not an authority (ADR 0006): its output is accepted only when it is complete
and consistent with the request and the net. Anything else becomes ERROR for every formula, never
a verdict (CLAUDE.md, domain rule 1).
"""

from __future__ import annotations

from .contract import ElementRef, Marking, MarkingEntry
from .engine_contract import EngineReport, ReportedResult, Trace, TraceStep
from .models import CheckRequest, DomainModel, FormulaResult, Verdict
from .net_structure import NetStructure


class CheckOutcome(DomainModel):
    """The results of a check, and the counterexamples that go with them."""

    results: tuple[FormulaResult, ...]
    traces: tuple[Trace, ...] = ()


def initial_marking_of(*, structure: NetStructure) -> Marking:
    """Return the initial marking of a P/T net (empty for other kinds of net)."""
    return Marking(
        entries=tuple(
            MarkingEntry(
                place=ElementRef(id=node.id, name=node.name, kind="place"), tokens=node.tokens
            )
            for node in structure.places
            if node.tokens
        )
    )


def all_error(*, request: CheckRequest, engine: str, warning: str) -> CheckOutcome:
    """Report ERROR for every formula with the reason: the engine produced nothing usable."""
    return CheckOutcome(
        results=tuple(
            FormulaResult(id=formula.id, verdict=Verdict.ERROR, engine=engine, warnings=(warning,))
            for formula in request.formulas
        )
    )


def find_problem(
    *, report: EngineReport, request: CheckRequest, structure: NetStructure
) -> str | None:
    """Return the first reason why an engine output cannot be trusted, or None."""
    if not report.tool_version:
        return "the envelope does not name the tool version"
    requested = {formula.id for formula in request.formulas}
    seen: set[str] = set()
    transitions = {node.id for node in structure.transitions}
    for reported in report.results:
        formula_id = reported.result.id
        if formula_id not in requested:
            return f"result for unknown formula {formula_id!r}"
        if formula_id in seen:
            return f"two results for formula {formula_id!r}"
        seen.add(formula_id)
        trace = reported.trace
        if trace is None:
            continue
        for index, step in enumerate(trace.steps):
            if step.transition not in transitions:
                return (
                    f"trace of {formula_id!r} step {index} cites {step.transition!r}, "
                    "which is not a transition of the net"
                )
        if trace.loop_start is not None and trace.loop_start >= len(trace.steps):
            return f"trace of {formula_id!r} starts its loop after its last step"
    return None


def interpret_report(
    *,
    report: EngineReport,
    request: CheckRequest,
    engine: str,
    net_id: str,
    structure: NetStructure,
) -> CheckOutcome:
    """Turn an engine report into results, or into ERROR for every formula if it is not usable."""
    if report.status == "failed":
        return all_error(
            request=request, engine=engine, warning=f"engine_failed: {report.error_code}"
        )
    problem = find_problem(report=report, request=request, structure=structure)
    if problem is not None:
        return all_error(
            request=request, engine=engine, warning=f"invalid_engine_output: {problem}"
        )

    by_id: dict[str, ReportedResult] = {item.result.id: item for item in report.results}
    initial = initial_marking_of(structure=structure)
    nodes = {node.id: node for node in structure.transitions}
    results: list[FormulaResult] = []
    traces: list[Trace] = []
    for formula in request.formulas:
        reported = by_id.get(formula.id)
        if reported is None:
            results.append(
                FormulaResult(
                    id=formula.id,
                    verdict=Verdict.ERROR,
                    engine=engine,
                    engine_version=report.tool_version or "unknown",
                    warnings=("missing_in_engine_output",),
                )
            )
            continue
        warnings = reported.result.warnings
        if report.status == "partial":
            warnings = (*warnings, "engine_partial")
        results.append(
            FormulaResult(
                id=formula.id,
                verdict=reported.result.verdict,
                engine=engine,
                engine_version=report.tool_version or "unknown",
                time_s=reported.result.time_s,
                rendered=reported.result.rendered,
                warnings=warnings,
            )
        )
        if reported.trace is not None:
            traces.append(
                Trace(
                    formula_id=formula.id,
                    net_id=net_id,
                    initial_marking=initial,
                    steps=tuple(
                        TraceStep(
                            transition=ElementRef(
                                id=step.transition,
                                name=nodes[step.transition].name,
                                kind="transition",
                            )
                        )
                        for step in reported.trace.steps
                    ),
                    loop_start=reported.trace.loop_start,
                )
            )
    return CheckOutcome(results=tuple(results), traces=tuple(traces))
