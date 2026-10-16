"""Audit the stored sessions: no verdict without an engine result behind it (measure M1)."""

from __future__ import annotations

from app.domain.errors import NotFoundError
from app.domain.models import Job
from app.domain.sessions import StoredEvent, Verdict
from app.domain.soundness import SoundnessReport, audit_session, merge_reports

from .ports import JobRepository, SessionRepository

PAGE = 500


class SoundnessAuditor:
    """Read sessions and the jobs their verdicts cite, and report what does not hold."""

    def __init__(self, *, sessions: SessionRepository, jobs: JobRepository) -> None:
        """Create the auditor over the stores of sessions and jobs."""
        self._sessions = sessions
        self._jobs = jobs

    def audit(self, *, session_ids: tuple[str, ...] | None) -> SoundnessReport:
        """Audit the given sessions, or every session when none is named."""
        ids = self._sessions.session_ids() if session_ids is None else session_ids
        reports = []
        for session_id in ids:
            events: list[StoredEvent] = []
            while True:
                page = self._sessions.events_after(
                    session_id=session_id, after=events[-1].number if events else 0, limit=PAGE
                )
                events.extend(page)
                if len(page) < PAGE:
                    break
            cited = sorted({e.event.job_id for e in events if isinstance(e.event, Verdict)})
            jobs: list[Job] = []
            for job_id in cited:
                try:
                    jobs.append(self._jobs.load_job(job_id=job_id))
                except NotFoundError:
                    continue  # the audit reports the verdict that cites it
            reports.append(
                audit_session(session_id=session_id, events=tuple(events), jobs=tuple(jobs))
            )
        return merge_reports(reports=tuple(reports))
