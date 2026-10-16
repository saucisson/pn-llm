"""Measures of the user study that the session log gives (M10, docs/user-study.md).

Only what the events can say is computed here: how long until an engine first returned a TRUE or
a FALSE, how many questions the assistant asked, how many properties it proposed, and how often
each verdict came back. Whether a property was *useful* and whether the participant read UNKNOWN
and TIMEOUT correctly are answers of the participant, collected by the protocol, not inferred.
"""

from __future__ import annotations

from .models import DomainModel
from .sessions import PropertyProposed, Question, StoredEvent, Verdict


class VerdictCount(DomainModel):
    """How many times an engine returned a verdict in the session."""

    verdict: str
    count: int


class SessionMeasures(DomainModel):
    """What the log of one session shows of the interaction."""

    session_id: str
    duration_s: float
    # Seconds from the start to the first definitive verdict; None if none came.
    first_definitive_verdict_s: float | None
    properties: int
    questions: int
    verdicts: tuple[VerdictCount, ...]


def measure_session(*, session_id: str, events: tuple[StoredEvent, ...]) -> SessionMeasures:
    """Read the interaction measures from the events of a session."""
    if not events:
        return SessionMeasures(
            session_id=session_id,
            duration_s=0.0,
            first_definitive_verdict_s=None,
            properties=0,
            questions=0,
            verdicts=(),
        )
    start = events[0].at
    first: float | None = None
    counts: dict[str, int] = {}
    for stored in events:
        event = stored.event
        if isinstance(event, Verdict):
            counts[event.verdict.value] = counts.get(event.verdict.value, 0) + 1
            if first is None and event.verdict.value in {"TRUE", "FALSE"}:
                first = stored.at - start
    return SessionMeasures(
        session_id=session_id,
        duration_s=events[-1].at - start,
        first_definitive_verdict_s=first,
        properties=sum(isinstance(e.event, PropertyProposed) for e in events),
        questions=sum(isinstance(e.event, Question) for e in events),
        verdicts=tuple(VerdictCount(verdict=v, count=n) for v, n in sorted(counts.items())),
    )
