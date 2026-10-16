"""Domain models. Every piece of data in the system is one of these immutable pydantic models.

They also serve as the tool schema exposed to the LLM through the OpenAPI document.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .base import DomainModel
from .formula import Formula

__all__ = ["DomainModel"]  # re-exported: most modules import it from here


class Verdict(StrEnum):
    """Outcome of one verification. UNKNOWN must never be confused with FALSE."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"
    TIMEOUT = "TIMEOUT"
    OOM = "OOM"
    ERROR = "ERROR"


class JobState(StrEnum):
    """Lifecycle of a check job."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # the API restarted while the job was queued or running


class Limits(DomainModel):
    """Resource limits applied to one engine run."""

    timeout_s: int = Field(default=300, ge=1, le=3600)
    memory_mb: int = Field(default=4096, ge=64, le=65536)


class CheckRequest(DomainModel):
    """Body of ``POST /v1/nets/{id}/checks``."""

    formulas: tuple[Formula, ...] = Field(min_length=1)
    engine: str = "auto"
    limits: Limits = Field(default_factory=Limits)
    # Let the engine reduce the net internally (most do, whatever is asked). False asks it not to,
    # to compare: an engine that cannot switch its reductions off says so in a warning.
    reduce: bool = True
    # With ``engine: auto``: how many of the best engines to run at the same time (a portfolio).
    portfolio: int = Field(default=1, ge=1, le=4)
    # Wait for every engine of the portfolio and compare their verdicts, instead of stopping the
    # others at the first definitive answer to every formula.
    cross_check: bool = False

    @model_validator(mode="after")
    def _formula_ids_are_unique(self) -> CheckRequest:
        """Reject two formulas with the same id: results are reported by id."""
        ids = [formula.id for formula in self.formulas]
        if len(set(ids)) != len(ids):
            message = "formula ids must be unique"
            raise ValueError(message)
        if self.portfolio > 1 and self.engine != "auto":
            message = "a portfolio chooses its engines: use engine auto"
            raise ValueError(message)
        return self


class EngineAnswer(DomainModel):
    """What one engine answered for a formula, kept as evidence when several engines were asked."""

    engine: str
    engine_version: str = "unknown"
    verdict: Verdict
    time_s: float = 0.0
    warnings: tuple[str, ...] = ()
    has_trace: bool = False


class FormulaResult(DomainModel):
    """Verdict of one formula, with the engine that produced it."""

    id: str
    verdict: Verdict
    engine: str
    engine_version: str = "unknown"
    time_s: float = 0.0
    # The formula in the engine's own syntax, recorded by the adapter for audit.
    rendered: str | None = None
    trace_url: str | None = None
    warnings: tuple[str, ...] = ()
    # With a portfolio: whether one engine answered (single), several agreed, or definitive
    # verdicts contradicted each other. A contradiction is never resolved silently (CLAUDE.md,
    # domain rule 8): the verdict is UNKNOWN unless a counterexample replayed on the net settles it.
    agreement: Literal["single", "agree", "contradiction"] = "single"
    arbitration: str | None = None
    alternatives: tuple[EngineAnswer, ...] = ()


class Job(DomainModel):
    """An asynchronous check of a set of formulas on one net."""

    job_id: str
    net_id: str
    state: JobState
    request: CheckRequest
    results: tuple[FormulaResult, ...] = ()


class JobSubmission(DomainModel):
    """Result of submitting a check: the job to use and whether it is new (to be executed)."""

    job: Job
    created: bool


class EngineInfo(DomainModel):
    """Capabilities and availability of one engine."""

    name: str
    version: str
    logics: tuple[str, ...]
    supports_colored: bool = False
    # The analyses and reductions the engine performs, by name (ADR 0014).
    operations: tuple[str, ...] = ()
    # The contest examinations the engine takes part in, and the classes of properties it checks.
    examinations: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    # What is known to be different or missing, as the adapter and the tool behave.
    limitations: tuple[str, ...] = ()
    available: bool
