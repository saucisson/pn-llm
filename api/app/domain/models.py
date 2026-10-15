"""Domain models. Every piece of data in the system is one of these immutable pydantic models.

They also serve as the tool schema exposed to the LLM through the OpenAPI document.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Base class of all models: immutable, so that no function can change its inputs."""

    model_config = ConfigDict(frozen=True)


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


class Formula(DomainModel):
    """A property to check, with its origin for later evaluation."""

    id: str
    syntax: Literal["ltl", "ctl", "reachability", "deadlock", "bounds"] = "ltl"
    text: str
    origin: Literal["user", "llm", "template"] = "user"


class Limits(DomainModel):
    """Resource limits applied to one engine run."""

    timeout_s: int = Field(default=300, ge=1, le=3600)
    memory_mb: int = Field(default=4096, ge=64, le=65536)


class CheckRequest(DomainModel):
    """Body of ``POST /v1/nets/{id}/checks``."""

    formulas: tuple[Formula, ...] = Field(min_length=1)
    engine: str = "auto"
    limits: Limits = Field(default_factory=Limits)


class FormulaResult(DomainModel):
    """Verdict of one formula, with the engine that produced it."""

    id: str
    verdict: Verdict
    engine: str
    engine_version: str = "unknown"
    time_s: float = 0.0
    trace_url: str | None = None
    warnings: tuple[str, ...] = ()


class EngineOutput(DomainModel):
    """Content of ``result.json`` written by an engine container (see docs/engine-contract.md)."""

    results: tuple[FormulaResult, ...]


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
    syntaxes: tuple[str, ...]
    supports_colored: bool = False
    available: bool
