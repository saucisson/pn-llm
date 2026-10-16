"""SQLite persistence of nets and jobs (standard library only).

Implements the ``NetRepository`` and ``JobRepository`` ports. One short-lived connection per
operation: safe with FastAPI's thread pool and with several API processes on the same host. WAL
mode lets readers and writers work concurrently; every state change is one atomic conditional
UPDATE, so processes never need to coordinate outside the database.

Liveness uses leases: a queued or running job carries an expiry that its owner keeps renewing.
Any process may mark a job whose lease expired as interrupted.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import zlib

from pydantic import TypeAdapter

from app.domain.canonical import canonical_bytes
from app.domain.descriptions import (
    Description,
    DescriptionOrigin,
    SavedDescription,
    description_id_of,
)
from app.domain.engine_contract import Trace
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import CheckRequest, FormulaResult, Job, JobState, JobSubmission
from app.domain.net_document import NetDocument
from app.domain.nets import NetSummary, SavedNet, StoredNet
from app.domain.sessions import (
    Session,
    SessionEvent,
    SessionState,
    StartedSession,
    StoredEvent,
)

from .sqlite_database import SqliteDatabase

_RESULTS = TypeAdapter(tuple[FormulaResult, ...])
_EVENT: TypeAdapter[SessionEvent] = TypeAdapter(SessionEvent)


def _session_from_row(*, row: sqlite3.Row) -> Session:
    """Build a session from a database row."""
    return Session(
        session_id=row["session_id"],
        net_id=row["net_id"],
        description_id=row["description_id"],
        state=SessionState(row["state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqliteStore(SqliteDatabase):
    """Nets, jobs, descriptions, sessions and their events, persisted in one SQLite file."""

    @staticmethod
    def _job_from_row(*, row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            net_id=row["net_id"],
            state=JobState(row["state"]),
            request=CheckRequest.model_validate_json(row["request"]),
            results=_RESULTS.validate_json(row["results"]),
        )

    # ---- NetRepository --------------------------------------------------------------------

    def save_net(self, *, summary: NetSummary, document: NetDocument) -> SavedNet:
        """Store a net if it is new; return what is stored (the existing net if already known)."""
        compressed = zlib.compress(canonical_bytes(document=document))
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO nets(net_id, summary, document, created_at)"
                " VALUES (?,?,?,?)",
                (summary.net_id, summary.model_dump_json(), compressed, time.time()),
            )
            created = cursor.rowcount == 1
        return SavedNet(stored=self.load_net(net_id=summary.net_id), created=created)

    def load_net(self, *, net_id: str) -> StoredNet:
        """Return a stored net, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT summary, document FROM nets WHERE net_id=?", (net_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown net: {net_id}")
        return StoredNet(
            summary=NetSummary.model_validate_json(row["summary"]),
            document=NetDocument.model_validate_json(zlib.decompress(row["document"])),
        )

    # ---- DescriptionRepository ------------------------------------------------------------

    def save_description(
        self, *, net_id: str, text: str, origin: DescriptionOrigin
    ) -> SavedDescription:
        """Store a description and link it to a net; adding the same text twice is a no-op."""
        description_id = description_id_of(text=text)
        now = time.time()
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO descriptions(description_id, text, created_at)"
                " VALUES (?,?,?)",
                (description_id, text, now),
            )
            cursor = conn.execute(
                "INSERT OR IGNORE INTO net_descriptions(net_id, description_id, origin, created_at)"
                " VALUES (?,?,?,?)",
                (net_id, description_id, origin, now),
            )
        return SavedDescription(
            description=Description(
                description_id=description_id, net_id=net_id, origin=origin, text=text
            ),
            created=cursor.rowcount == 1,
        )

    def descriptions_of(self, *, net_id: str) -> tuple[Description, ...]:
        """Return the descriptions linked to a net, oldest first."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT d.description_id, d.text, l.origin FROM net_descriptions l"
                " JOIN descriptions d USING (description_id) WHERE l.net_id=?"
                " ORDER BY l.created_at, d.description_id",
                (net_id,),
            ).fetchall()
        return tuple(
            Description(
                description_id=row["description_id"],
                net_id=net_id,
                origin=row["origin"],
                text=row["text"],
            )
            for row in rows
        )

    def load_description(self, *, description_id: str) -> tuple[Description, ...]:
        """Return a description with each of its links (one per net and origin)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT d.text, l.net_id, l.origin FROM descriptions d"
                " JOIN net_descriptions l USING (description_id) WHERE d.description_id=?"
                " ORDER BY l.created_at, l.net_id",
                (description_id,),
            ).fetchall()
        if not rows:
            raise NotFoundError(f"Unknown description: {description_id}")
        return tuple(
            Description(
                description_id=description_id,
                net_id=row["net_id"],
                origin=row["origin"],
                text=row["text"],
            )
            for row in rows
        )

    # ---- SessionRepository ----------------------------------------------------------------

    def create_session(self, *, session: Session, started: SessionEvent) -> StartedSession:
        """Store a new session and its first event together."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO sessions(session_id, net_id, description_id, state, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?)",
                (
                    session.session_id,
                    session.net_id,
                    session.description_id,
                    session.state.value,
                    session.created_at,
                    session.updated_at,
                ),
            )
            conn.execute(
                "INSERT INTO events(session_id, number, at, kind, body) VALUES (?,?,?,?,?)",
                (
                    session.session_id,
                    1,
                    session.created_at,
                    started.kind,
                    _EVENT.dump_json(started).decode(),
                ),
            )
        first = StoredEvent(
            session_id=session.session_id, number=1, at=session.created_at, event=started
        )
        return StartedSession(session=session, first_event=first)

    def session_ids(self) -> tuple[str, ...]:
        """Return the id of every session, oldest first."""
        with self._connection() as conn:
            rows = conn.execute("SELECT session_id FROM sessions ORDER BY created_at").fetchall()
        return tuple(row["session_id"] for row in rows)

    def load_session(self, *, session_id: str) -> Session:
        """Return a session, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown session: {session_id}")
        return _session_from_row(row=row)

    def append_event(self, *, session_id: str, event: SessionEvent) -> StoredEvent:
        """Add an event with the next number of the session (strictly increasing, no gap).

        The number is computed by the INSERT itself, under SQLite's write lock, so concurrent
        writers of any process get distinct consecutive numbers.
        """
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "INSERT INTO events(session_id, number, at, kind, body)"
                " SELECT ?, COALESCE(MAX(number), 0) + 1, ?, ?, ? FROM events WHERE session_id=?"
                " RETURNING number",
                (session_id, now, event.kind, _EVENT.dump_json(event).decode(), session_id),
            ).fetchone()
            conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        return StoredEvent(session_id=session_id, number=row["number"], at=now, event=event)

    def events_after(self, *, session_id: str, after: int, limit: int) -> tuple[StoredEvent, ...]:
        """Return up to ``limit`` events whose number is above ``after``, in order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT number, at, body FROM events WHERE session_id=? AND number>?"
                " ORDER BY number LIMIT ?",
                (session_id, after, limit),
            ).fetchall()
        return tuple(
            StoredEvent(
                session_id=session_id,
                number=row["number"],
                at=row["at"],
                event=_EVENT.validate_json(row["body"]),
            )
            for row in rows
        )

    def move_session(
        self, *, session_id: str, allowed_from: tuple[SessionState, ...], to: SessionState
    ) -> bool:
        """Change the state if it is one of ``allowed_from``; False if it was not."""
        marks = ",".join("?" for _ in allowed_from)
        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE sessions SET state=?, updated_at=? WHERE session_id=?"  # noqa: S608 - marks only
                f" AND state IN ({marks})",
                (to.value, time.time(), session_id, *(state.value for state in allowed_from)),
            )
            return cursor.rowcount == 1

    def claim_next_run(self, *, lease_seconds: float) -> Session | None:
        """Atomically claim the oldest queued session for this process; None if none waits."""
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "UPDATE sessions SET state='running', lease_expires_at=?, updated_at=?"
                " WHERE session_id = (SELECT session_id FROM sessions WHERE state='queued'"
                " ORDER BY updated_at, session_id LIMIT 1) AND state='queued' RETURNING *",
                (now + lease_seconds, now),
            ).fetchone()
        return None if row is None else _session_from_row(row=row)

    def renew_run_lease(self, *, session_id: str, lease_seconds: float) -> bool:
        """Extend the lease of a running session; False if it is no longer running."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET lease_expires_at=?, updated_at=?"
                " WHERE session_id=? AND state='running'",
                (now + lease_seconds, now, session_id),
            )
            return cursor.rowcount == 1

    def finish_run(self, *, session_id: str, to: SessionState) -> bool:
        """Leave the running state, only if the session is still running."""
        return self.move_session(session_id=session_id, allowed_from=(SessionState.RUNNING,), to=to)

    def requeue_lost_runs(self) -> int:
        """Queue again the running sessions whose lease expired: a run resumes from its events."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET state='queued', updated_at=?"
                " WHERE state='running' AND lease_expires_at < ?",
                (now, now),
            )
            return int(cursor.rowcount)

    def expire_waiting_sessions(self, *, older_than_s: float) -> tuple[str, ...]:
        """Cancel the sessions waiting for the user for longer than this; return their ids."""
        now = time.time()
        with self._connection() as conn:
            rows = conn.execute(
                "UPDATE sessions SET state='cancelled', updated_at=?"
                " WHERE state='waiting_for_user' AND updated_at < ? RETURNING session_id",
                (now, now - older_than_s),
            ).fetchall()
        return tuple(row["session_id"] for row in rows)

    # ---- JobRepository --------------------------------------------------------------------

    def create_or_get_job(self, *, job: Job) -> JobSubmission:
        """Insert ``job`` unless an equivalent live job exists; say which one must be used.

        A queued job has no owner and no lease: it waits in the queue for a worker.

        Safe under concurrent calls thanks to the unique index on live idempotency keys.
        """
        key = hashlib.sha256(f"{job.net_id}|{job.request.model_dump_json()}".encode()).hexdigest()
        now = time.time()
        while True:
            try:
                with self._connection() as conn:
                    conn.execute(
                        "INSERT INTO jobs(job_id, net_id, job_key, state, request, results,"
                        " lease_expires_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            job.job_id,
                            job.net_id,
                            key,
                            job.state.value,
                            job.request.model_dump_json(),
                            _RESULTS.dump_json(job.results).decode(),
                            0.0,
                            now,
                            now,
                        ),
                    )
                return JobSubmission(job=job, created=True)
            except sqlite3.IntegrityError:
                with self._connection() as conn:
                    row = conn.execute(
                        "SELECT * FROM jobs WHERE job_key=?"
                        " AND state IN ('queued','running','done')"
                        " ORDER BY created_at DESC LIMIT 1",
                        (key,),
                    ).fetchone()
                if row is not None:
                    return JobSubmission(job=self._job_from_row(row=row), created=False)
                # The live job finished or was cancelled between the two statements: try again.

    def load_job(self, *, job_id: str) -> Job:
        """Return a job, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown job: {job_id}")
        return self._job_from_row(row=row)

    def claim_next_job(self, *, lease_seconds: float) -> Job | None:
        """Atomically claim the oldest queued job for this process, or return None if none waits.

        One conditional UPDATE picks and claims in the same statement, so of several workers
        looking at the same job exactly one gets it.
        """
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "UPDATE jobs SET state='running', lease_expires_at=?, updated_at=?"
                " WHERE job_id = (SELECT job_id FROM jobs WHERE state='queued'"
                " ORDER BY created_at, job_id LIMIT 1) AND state='queued' RETURNING job_id",
                (now + lease_seconds, now),
            ).fetchone()
        return None if row is None else self.load_job(job_id=row["job_id"])

    def requeue(self, *, job_id: str) -> bool:
        """Put an interrupted job back in the queue; return False if it was not interrupted.

        Raises:
            ConflictError: if an equivalent job is live, which holds the idempotency key.
        """
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET state='queued', updated_at=?"
                    " WHERE job_id=? AND state='interrupted'",
                    (time.time(), job_id),
                )
                return cursor.rowcount == 1
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                f"An equivalent job is already live; job {job_id} stays interrupted"
            ) from exc

    def renew_lease(self, *, job_id: str, lease_seconds: float) -> bool:
        """Extend the lease of a running job; return False if it is no longer running."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET lease_expires_at=?, updated_at=?"
                " WHERE job_id=? AND state='running'",
                (now + lease_seconds, now, job_id),
            )
            return cursor.rowcount == 1

    def cancel(self, *, job_id: str) -> None:
        """Cancel a queued or running job; finished jobs keep their state and results."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE jobs SET state='cancelled', updated_at=?"
                " WHERE job_id=? AND state IN ('queued','running')",
                (time.time(), job_id),
            )

    def finish(
        self, *, job_id: str, results: tuple[FormulaResult, ...], traces: tuple[Trace, ...]
    ) -> None:
        """Store results and counterexamples and mark the job done, only if it is still running."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET results=?, state='done', updated_at=?"
                " WHERE job_id=? AND state='running'",
                (_RESULTS.dump_json(results).decode(), time.time(), job_id),
            )
            if cursor.rowcount != 1:
                return  # cancelled or interrupted meanwhile: its answer is not wanted
            conn.executemany(
                "INSERT OR REPLACE INTO traces(job_id, formula_id, trace) VALUES (?,?,?)",
                [
                    (job_id, trace.formula_id, zlib.compress(trace.model_dump_json().encode()))
                    for trace in traces
                ],
            )

    def load_trace(self, *, job_id: str, formula_id: str) -> Trace:
        """Return the counterexample stored for a formula of a job, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT trace FROM traces WHERE job_id=? AND formula_id=?", (job_id, formula_id)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"No trace for formula {formula_id!r} of job {job_id}")
        return Trace.model_validate_json(zlib.decompress(row["trace"]))

    def purge_finished_jobs(self, *, older_than_s: float) -> int:
        """Delete finished jobs (and their traces) not touched for ``older_than_s`` seconds.

        Queued and running jobs are never deleted, and nets are never deleted: they are immutable
        and may be used again.
        """
        cutoff = time.time() - older_than_s
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM traces WHERE job_id IN (SELECT job_id FROM jobs"
                " WHERE state IN ('done','cancelled','interrupted') AND updated_at < ?)",
                (cutoff,),
            )
            cursor = conn.execute(
                "DELETE FROM jobs WHERE state IN ('done','cancelled','interrupted')"
                " AND updated_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

    def recover_interrupted(self) -> int:
        """Mark running jobs whose lease expired as interrupted; return their count.

        Safe to call from any process at any time: a job whose owner is alive keeps renewing its
        lease and is never touched.
        """
        now = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET state='interrupted', updated_at=?"
                " WHERE state='running' AND lease_expires_at < ?",
                (now, now),
            )
            return int(cursor.rowcount)
