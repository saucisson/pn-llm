"""Read the whole event log of a session from its store."""

from __future__ import annotations

from app.domain.sessions import StoredEvent

from .ports import SessionRepository

PAGE = 500


def read_events(*, sessions: SessionRepository, session_id: str) -> tuple[StoredEvent, ...]:
    """Return every event of a session, in order."""
    events: list[StoredEvent] = []
    while True:
        page = sessions.events_after(
            session_id=session_id, after=events[-1].number if events else 0, limit=PAGE
        )
        events.extend(page)
        if len(page) < PAGE:
            return tuple(events)
