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
import zlib
from collections.abc import Iterator
from pathlib import Path

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

from .sqlite_migrations import migrate

_RESULTS = TypeAdapter(tuple[FormulaResult, ...])


class SqliteStore:
    """Nets and jobs, persisted in one SQLite file."""

    def __init__(self, *, path: Path) -> None:
        """Open (and create if needed) the database at ``path``."""
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        migrate(path=path)

    @contextlib.contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            # The write-ahead mode is stored in the file by the migration: nothing to switch here.
            conn.execute("PRAGMA foreign_keys=ON")
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
