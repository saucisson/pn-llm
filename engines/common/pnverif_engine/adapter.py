"""Adapter kit: read the request, run the tool, write the result envelope.

An adapter is a small program that follows ``docs/engine-contract.md``. This kit does the parts
that are the same for every tool: reading ``request.json``, timing, turning the tool's wording of
a verdict into one of ours without ever inventing TRUE or FALSE, writing ``result.json`` and
the trace files, and turning any crash into a ``failed`` envelope instead of a missing file.
The adapter itself only translates formulas to the tool's syntax and the tool's output back.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from pydantic import JsonValue

from app.domain.contract import Envelope, ErrorInfo, ToolInfo
from app.domain.engine_contract import (
    EngineCheckData,
    EngineFormulaResult,
    EngineOperationData,
    EngineRequest,
    EngineTrace,
    EngineTraceStep,
)
from app.domain.models import DomainModel, Verdict

DEFAULT_WORK_DIR = Path("/work")

TRUE_WORDS = frozenset({"true", "yes", "satisfied", "holds", "sat"})
FALSE_WORDS = frozenset({"false", "no", "violated", "unsat"})


class AdapterInput(DomainModel):
    """What the tool-specific part of an adapter receives."""

    request: EngineRequest
    net_path: Path
    output_dir: Path


class AdapterAnswer(DomainModel):
    """The tool-specific part's answer for one formula."""

    formula_id: str
    verdict: Verdict
    # The formula in the tool's own syntax, kept for audit.
    rendered: str | None = None
    time_s: float = 0.0
    # Ids of the transitions fired by the counterexample, if the tool gave one.
    trace: tuple[str, ...] | None = None
    loop_start: int | None = None
    warnings: tuple[str, ...] = ()


class OperationAnswer(DomainModel):
    """The tool-specific part's answer for an analysis or a reduction."""

    # The operation's result model, dumped as JSON.
    result: JsonValue
    warnings: tuple[str, ...] = ()


def normalize_verdict(*, raw: str | bool | None) -> Verdict:
    """Translate a tool's wording of an answer into a verdict.

    Only clear words become TRUE or FALSE. Everything else, including "cannot compute", a
    timeout message or an empty answer, is UNKNOWN: never FALSE (CLAUDE.md, domain rule 1).
    """
    if isinstance(raw, bool):
        return Verdict.TRUE if raw else Verdict.FALSE
    word = (raw or "").strip().lower()
    if word in TRUE_WORDS:
        return Verdict.TRUE
    if word in FALSE_WORDS:
        return Verdict.FALSE
    return Verdict.UNKNOWN


def read_request(*, work_dir: Path = DEFAULT_WORK_DIR) -> EngineRequest:
    """Read and validate ``request.json`` from the input directory."""
    return EngineRequest.model_validate_json((work_dir / "input" / "request.json").read_text())


def trace_file_name(*, index: int) -> str:
    """Return the name of the trace file of the ``index``-th formula."""
    return f"trace_{index}.json"


def store_envelope(*, output_dir: Path, envelope: Envelope[EngineCheckData]) -> None:
    """Write ``result.json``."""
    (output_dir / "result.json").write_text(envelope.model_dump_json())


def write_result(
    *,
    output_dir: Path,
    request: EngineRequest,
    tool: ToolInfo,
    answers: tuple[AdapterAnswer, ...],
    elapsed_s: float,
) -> None:
    """Write ``result.json`` and the trace files for the answers of a check.

    There is exactly one entry per formula of the request, in its order: a formula the tool did
    not answer gets ERROR, and an answer for an unknown formula is dropped (the platform would
    reject the whole output).
    """
    by_id = {answer.formula_id: answer for answer in answers}
    entries: list[EngineFormulaResult] = []
    for index, formula in enumerate(request.formulas):
        answer = by_id.get(formula.id)
        if answer is None:
            entries.append(
                EngineFormulaResult(
                    id=formula.id, verdict=Verdict.ERROR, warnings=("no_answer_from_tool",)
                )
            )
            continue
        trace_name = None
        if answer.trace is not None:
            trace_name = trace_file_name(index=index)
            trace = EngineTrace(
                steps=tuple(EngineTraceStep(transition=step) for step in answer.trace),
                loop_start=answer.loop_start,
            )
            (output_dir / trace_name).write_text(trace.model_dump_json())
        entries.append(
            EngineFormulaResult(
                id=formula.id,
                verdict=answer.verdict,
                time_s=answer.time_s,
                rendered=answer.rendered,
                trace=trace_name,
                warnings=answer.warnings,
            )
        )
    store_envelope(
        output_dir=output_dir,
        envelope=Envelope[EngineCheckData](
            tool=tool,
            net_id=request.net_id,
            status="ok",
            data=EngineCheckData(results=tuple(entries)),
            elapsed_s=elapsed_s,
        ),
    )


def write_failure(
    *,
    output_dir: Path,
    request: EngineRequest,
    tool: ToolInfo,
    error: ErrorInfo,
    elapsed_s: float,
) -> None:
    """Write a ``failed`` envelope: the run produced no answer, and says why."""
    store_envelope(
        output_dir=output_dir,
        envelope=Envelope[EngineCheckData](
            tool=tool,
            net_id=request.net_id,
            status="failed",
            error=error,
            elapsed_s=elapsed_s,
        ),
    )


def write_operation_result(
    *,
    output_dir: Path,
    request: EngineRequest,
    tool: ToolInfo,
    answer: OperationAnswer,
    elapsed_s: float,
) -> None:
    """Write ``result.json`` for an analysis or a reduction."""
    (output_dir / "result.json").write_text(
        Envelope[EngineOperationData](
            tool=tool,
            net_id=request.net_id,
            status="ok",
            data=EngineOperationData(result=answer.result),
            warnings=answer.warnings,
            elapsed_s=elapsed_s,
        ).model_dump_json()
    )


def run_adapter(
    *,
    tool_name: str,
    tool_version: str,
    check: Callable[[AdapterInput], tuple[AdapterAnswer, ...]] | None = None,
    operate: Callable[[AdapterInput], OperationAnswer] | None = None,
    work_dir: Path = DEFAULT_WORK_DIR,
) -> None:
    """Run a whole adapter: read the request, call ``check`` or ``operate``, write the envelope.

    A crash in either is caught and written as a ``failed`` envelope, so the platform always
    finds a result file (and reports ERROR, not a guess). A request of a kind the adapter does
    not handle is a failure too.
    """
    started = time.monotonic()
    tool = ToolInfo(name=tool_name, version=tool_version)
    request = read_request(work_dir=work_dir)
    output_dir = work_dir / "output"
    given = AdapterInput(
        request=request, net_path=work_dir / "input" / "net.pnml", output_dir=output_dir
    )
    try:
        if request.kind == "check" and check is not None:
            answers = check(given)
            write_result(
                output_dir=output_dir,
                request=request,
                tool=tool,
                answers=answers,
                elapsed_s=time.monotonic() - started,
            )
        elif request.kind == "analysis" and operate is not None:
            write_operation_result(
                output_dir=output_dir,
                request=request,
                tool=tool,
                answer=operate(given),
                elapsed_s=time.monotonic() - started,
            )
        else:
            write_failure(
                output_dir=output_dir,
                request=request,
                tool=tool,
                error=ErrorInfo(
                    code="unsupported_kind", message=f"this engine does not do {request.kind}"
                ),
                elapsed_s=time.monotonic() - started,
            )
    except Exception as exc:  # noqa: BLE001 - any crash of the tool part becomes a failed envelope
        write_failure(
            output_dir=output_dir,
            request=request,
            tool=tool,
            error=ErrorInfo(code="adapter_exception", message=f"{type(exc).__name__}: {exc}"),
            elapsed_s=time.monotonic() - started,
        )
