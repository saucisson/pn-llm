"""Audit of a session log: every verdict must stand on an engine result (measure M1).

The platform already refuses to build a verdict without an engine, a version and a job. This audit
checks the stored logs against the stored jobs afterwards, so a defect (a bug, a hand-edited log)
shows up as a failure and not as a number to optimise (docs/evaluation.md). It also lists the
contradictions between engines found in the jobs the sessions used: they are reported, never
resolved.
"""

from __future__ import annotations

from typing import Literal

from pydantic import computed_field

from .models import DomainModel, EngineAnswer, Job, JobState
from .sessions import StoredEvent, Verdict

FindingKind = Literal[
    "job_not_found",
    "result_not_found",
    "job_not_finished",
    "verdict_differs_from_result",
    "formula_differs_from_result",
    "engine_differs_from_result",
    "version_not_recorded",
    "trace_flag_differs_from_result",
]


class Finding(DomainModel):
    """One verdict of a log that does not stand on an engine result."""

    session_id: str
    event_number: int
    kind: FindingKind
    detail: str


class Contradiction(DomainModel):
    """Engines gave opposite definitive answers to one formula: a case for triage."""

    session_id: str
    job_id: str
    formula_id: str
    answers: tuple[EngineAnswer, ...]


class SoundnessReport(DomainModel):
    """What the audit looked at and what it found."""

    sessions: int
    verdict_events: int
    findings: tuple[Finding, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented decorator order
    @property
    def sound(self) -> bool:
        """True when no verdict is unsupported."""
        return not self.findings


def audit_session(
    *, session_id: str, events: tuple[StoredEvent, ...], jobs: tuple[Job, ...]
) -> SoundnessReport:
    """Check the verdict events of one session against the jobs they refer to."""
    by_id = {job.job_id: job for job in jobs}
    findings: list[Finding] = []
    contradictions: dict[tuple[str, str], Contradiction] = {}
    count = 0
    for stored in events:
        event = stored.event
        if not isinstance(event, Verdict):
            continue
        count += 1

        def flag(*, kind: FindingKind, detail: str, number: int = stored.number) -> None:
            findings.append(
                Finding(session_id=session_id, event_number=number, kind=kind, detail=detail)
            )

        job = by_id.get(event.job_id)
        if job is None:
            flag(kind="job_not_found", detail=f"no job {event.job_id!r} behind the verdict")
            continue
        if job.state is not JobState.DONE:
            flag(kind="job_not_finished", detail=f"job {job.job_id!r} is {job.state.value}")
            continue
        if event.result_index >= len(job.results):
            flag(kind="result_not_found", detail=f"job {job.job_id!r} has no such result")
            continue
        result = job.results[event.result_index]
        if result.id != event.formula_id:
            flag(
                kind="formula_differs_from_result",
                detail=f"the verdict names {event.formula_id!r}, the result {result.id!r}",
            )
        if result.verdict.value != event.verdict.value:
            flag(
                kind="verdict_differs_from_result",
                detail=f"the log says {event.verdict.value}, the engine {result.verdict.value}",
            )
        if result.engine != event.engine:
            flag(
                kind="engine_differs_from_result",
                detail=f"the log names {event.engine!r}, the result {result.engine!r}",
            )
        if (
            result.engine_version in {"", "unknown"}
            or event.engine_version != result.engine_version
        ):
            flag(
                kind="version_not_recorded",
                detail=f"engine version {event.engine_version!r} against {result.engine_version!r}",
            )
        if event.has_trace != (result.trace_url is not None):
            flag(
                kind="trace_flag_differs_from_result",
                detail="the log and the result disagree on whether a counterexample exists",
            )
        if result.agreement == "contradiction":
            contradictions[(job.job_id, result.id)] = Contradiction(
                session_id=session_id,
                job_id=job.job_id,
                formula_id=result.id,
                answers=result.alternatives,
            )
    return SoundnessReport(
        sessions=1,
        verdict_events=count,
        findings=tuple(findings),
        contradictions=tuple(contradictions.values()),
    )


def merge_reports(*, reports: tuple[SoundnessReport, ...]) -> SoundnessReport:
    """Combine the reports of several sessions."""
    return SoundnessReport(
        sessions=sum(r.sessions for r in reports),
        verdict_events=sum(r.verdict_events for r in reports),
        findings=tuple(f for r in reports for f in r.findings),
        contradictions=tuple(c for r in reports for c in r.contradictions),
    )
