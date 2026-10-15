"""The contract between the platform and an engine container, version 1 (docs/engine-contract.md).

An engine reads ``request.json`` and writes ``result.json``, a result envelope whose ``data``
lists one result per formula, plus one ``trace_<id>.json`` per counterexample. Everything an
engine says is checked here before it becomes a result of the platform: an engine is a tool, not
an authority.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .contract import ElementRef, Marking
from .formula import Formula
from .models import DomainModel, Limits, Verdict

ENGINE_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class EngineRequest(DomainModel):
    """What the platform writes to ``request.json``."""

    schema_version: Literal["1.0"] = ENGINE_SCHEMA_VERSION
    kind: Literal["check", "analysis", "reduction"] = "check"
    net_id: str
    formulas: tuple[Formula, ...] = ()
    limits: Limits = Field(default_factory=Limits)
    # Analyses and reductions name the single operation to perform (ADR 0014).
    operation: str | None = None
    protected: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _kind_needs_its_fields(self) -> EngineRequest:
        """A check carries formulas; an analysis or a reduction names its operation."""
        if self.kind == "check" and not self.formulas:
            message = "a check needs at least one formula"
            raise ValueError(message)
        if self.kind != "check" and self.operation is None:
            message = f"a {self.kind} needs an operation"
            raise ValueError(message)
        return self


class EngineFormulaResult(DomainModel):
    """One entry of ``result.json``: the verdict of one formula."""

    id: str
    verdict: Verdict
    time_s: float = Field(default=0.0, ge=0)
    # The formula in the engine's own syntax, written by the adapter for audit.
    rendered: str | None = None
    # Name of the counterexample file, in the output directory.
    trace: str | None = Field(default=None, pattern=r"^trace_[A-Za-z0-9_.\-]+\.json$")
    warnings: tuple[str, ...] = ()


class EngineCheckData(DomainModel):
    """The ``data`` of the envelope of a check."""

    results: tuple[EngineFormulaResult, ...]


class EngineTraceStep(DomainModel):
    """One firing, as an engine writes it: the id of the transition."""

    transition: str


class EngineTrace(DomainModel):
    """A counterexample (or witness) in a ``trace_<id>.json`` file.

    ``loop_start`` is the index of the step where the cycle begins in an infinite run.
    """

    steps: tuple[EngineTraceStep, ...]
    loop_start: int | None = Field(default=None, ge=0)


class TraceStep(DomainModel):
    """One firing, as the platform reports it: the transition cited by reference."""

    transition: ElementRef


class Trace(DomainModel):
    """A counterexample on the original net, validated against it (docs/json-contract.md)."""

    formula_id: str
    net_id: str
    initial_marking: Marking
    steps: tuple[TraceStep, ...]
    loop_start: int | None = None


class ReportedResult(DomainModel):
    """A result as read from an engine run: the entry and, if any, its loaded trace."""

    result: EngineFormulaResult
    trace: EngineTrace | None = None


class EngineReport(DomainModel):
    """What one engine run produced, before the platform checks it.

    ``status`` and ``error`` come from the envelope; a run that produced no readable envelope is
    reported as ``failed`` with the reason in ``error_code``.
    """

    tool_name: str | None = None
    tool_version: str | None = None
    status: Literal["ok", "partial", "failed"]
    error_code: str | None = None
    results: tuple[ReportedResult, ...] = ()
