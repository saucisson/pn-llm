"""SQLite persistence of nets and jobs (standard library only).

Implements the ``NetRepository`` and ``JobRepository`` ports. One short-lived connection per
operation: safe with FastAPI's thread pool and with several API processes on the same host. WAL
mode lets readers and writers work concurrently; every state change is one atomic conditional
UPDATE, so processes never need to coordinate outside the database.

Liveness uses leases: a queued or running job carries an expiry that its owner keeps renewing.
Any process may mark a job whose lease expired as interrupted.
"""

from __future__ import annotations

import contextlib
import hashlib
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.errors import NotFoundError
from app.domain.models import (
    CheckRequest,
    FormulaResult,
    Job,
    JobState,
    JobSubmission,
    NetSummary,
    StoredNet,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS nets (
    net_id     TEXT PRIMARY KEY,
    summary    TEXT NOT NULL,          -- NetSummary as JSON
    pnml       BLOB NOT NULL,          -- original bytes, never modified (nets are immutable)
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    net_id     TEXT NOT NULL REFERENCES nets(net_id),
    job_key    TEXT NOT NULL,          -- idempotency key: hash(net_id, request)
    state      TEXT NOT NULL,
    request    TEXT NOT NULL,          -- CheckRequest as JSON
    results    TEXT NOT NULL DEFAULT '[]',
    lease_expires_at REAL NOT NULL,    -- a live job whose lease expired belongs to a dead process
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_net ON jobs(net_id);
-- At most one live job per idempotency key, even under concurrent submissions.
CREATE UNIQUE INDEX IF NOT EXISTS jobs_live_key ON jobs(job_key)
    WHERE state IN ('queued', 'running', 'done');
"""

_RESULTS = TypeAdapter(tuple[FormulaResult, ...])


class SqliteStore:
    """Nets and jobs, persisted in one SQLite file."""

    def __init__(self, *, path: Path) -> None:
        """Open (and create if needed) the database at ``path``."""
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    @contextlib.contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:  # commit on success, roll back on error
                yield conn
        finally:
            conn.close()

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

    def save_net(self, *, summary: NetSummary, pnml: bytes) -> StoredNet:
        """Store a net if it is new; return what is stored (the existing net if already known)."""
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO nets(net_id, summary, pnml, created_at) VALUES (?,?,?,?)",
                (summary.net_id, summary.model_dump_json(), pnml, time.time()),
            )
        return self.load_net(net_id=summary.net_id)

    def load_net(self, *, net_id: str) -> StoredNet:
        """Return a stored net, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT summary, pnml FROM nets WHERE net_id=?", (net_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown net: {net_id}")
        return StoredNet(
            summary=NetSummary.model_validate_json(row["summary"]), pnml=bytes(row["pnml"])
        )

    # ---- JobRepository --------------------------------------------------------------------

    def create_or_get_job(self, *, job: Job, lease_seconds: float) -> JobSubmission:
        """Insert ``job`` unless an equivalent live job exists; say which one must be used.

        The new job is leased for ``lease_seconds``: it must be claimed before then.

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
                            now + lease_seconds,
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

    def mark_running(self, *, job_id: str, lease_seconds: float) -> bool:
        """Claim a queued job for this process; return False if it was not queued.

        Atomic: of several processes claiming the same job, exactly one gets True.
        """
        now = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET state='running', lease_expires_at=?, updated_at=?"
                " WHERE job_id=? AND state='queued'",
                (now + lease_seconds, now, job_id),
            )
            return cursor.rowcount == 1

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

    def finish(self, *, job_id: str, results: tuple[FormulaResult, ...]) -> None:
        """Store results and mark the job done, only if it is still running."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE jobs SET results=?, state='done', updated_at=?"
                " WHERE job_id=? AND state='running'",
                (_RESULTS.dump_json(results).decode(), time.time(), job_id),
            )

    def recover_interrupted(self) -> int:
        """Mark live jobs whose lease expired as interrupted; return their count.

        Safe to call from any process at any time: a job whose owner is alive keeps renewing its
        lease and is never touched.
        """
        now = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET state='interrupted', updated_at=?"
                " WHERE state IN ('queued','running') AND lease_expires_at < ?",
                (now, now),
            )
            return int(cursor.rowcount)
