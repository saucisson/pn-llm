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

from app.domain.canonical import canonical_bytes, net_id_of
from app.domain.engine_contract import Trace
from app.domain.errors import InvalidNetError, NotFoundError
from app.domain.models import CheckRequest, FormulaResult, Job, JobState, JobSubmission
from app.domain.net_document import NetDocument
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetSummary, SavedNet, StoredNet, summarize_document
from app.domain.pnml_import import import_pnml

SCHEMA = """
CREATE TABLE IF NOT EXISTS nets (
    net_id     TEXT PRIMARY KEY,
    summary    TEXT NOT NULL,          -- NetSummary as JSON
    document   BLOB NOT NULL,          -- canonical NetDocument JSON, zlib-compressed, immutable
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
CREATE TABLE IF NOT EXISTS traces (
    job_id     TEXT NOT NULL REFERENCES jobs(job_id),
    formula_id TEXT NOT NULL,
    trace      BLOB NOT NULL,          -- Trace as JSON, zlib-compressed
    PRIMARY KEY (job_id, formula_id)
);
-- At most one live job per idempotency key, even under concurrent submissions.
CREATE UNIQUE INDEX IF NOT EXISTS jobs_live_key ON jobs(job_key)
    WHERE state IN ('queued', 'running', 'done');
"""

_RESULTS = TypeAdapter(tuple[FormulaResult, ...])


class StoreMigrationError(Exception):
    """Stored data cannot be migrated to the current schema; the database was left unchanged."""


def migrate_legacy_nets(*, path: Path) -> int:
    """Re-import the nets of a first-schema database as canonical documents; return how many.

    The first schema kept the uploaded PNML bytes under a hash of the file. Each net is imported
    again, gets its canonical id, and the jobs that point to it follow. All or nothing: a net that
    no longer imports (the rules are stricter now) aborts the migration and nothing changes.
    Migrated jobs get a fresh idempotency key, so two nets that collapse into one cannot collide.

    Raises:
        StoreMigrationError: if a stored net cannot be imported.
    """
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=OFF")  # jobs reference nets while we swap the table
        conn.execute("BEGIN IMMEDIATE")  # another process may be migrating: re-check inside
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(nets)")}
        if "pnml" not in columns:
            conn.execute("ROLLBACK")
            return 0
        limits = DocumentLimits()
        new_id_of: dict[str, str] = {}
        new_rows: list[tuple[str, str, bytes, float]] = []
        failures: list[str] = []
        for row in conn.execute("SELECT net_id, pnml, created_at FROM nets").fetchall():
            try:
                document = import_pnml(payload=bytes(row["pnml"]), limits=limits)
                new_id = net_id_of(document=document)
                summary = summarize_document(document=document, net_id=new_id)
            except InvalidNetError as exc:
                failures.append(f"{row['net_id']}: {exc}")
                continue
            new_id_of[row["net_id"]] = new_id
            new_rows.append(
                (
                    new_id,
                    summary.model_dump_json(),
                    zlib.compress(canonical_bytes(document=document)),
                    row["created_at"],
                )
            )
        if failures:
            conn.execute("ROLLBACK")
            raise StoreMigrationError(
                "These stored nets no longer import, nothing was migrated: " + "; ".join(failures)
            )
        conn.execute(
            "CREATE TABLE nets_new (net_id TEXT PRIMARY KEY, summary TEXT NOT NULL,"
            " document BLOB NOT NULL, created_at REAL NOT NULL)"
        )
        conn.executemany("INSERT OR IGNORE INTO nets_new VALUES (?,?,?,?)", new_rows)
        has_jobs = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if has_jobs:
            for job in conn.execute("SELECT job_id, net_id, request FROM jobs").fetchall():
                new_id = new_id_of[job["net_id"]]
                key = hashlib.sha256(
                    f"{new_id}|{job['request']}|{job['job_id']}".encode()
                ).hexdigest()
                conn.execute(
                    "UPDATE jobs SET net_id=?, job_key=? WHERE job_id=?",
                    (new_id, key, job["job_id"]),
                )
        conn.execute("DROP TABLE nets")
        conn.execute("ALTER TABLE nets_new RENAME TO nets")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(new_rows)


class SqliteStore:
    """Nets and jobs, persisted in one SQLite file."""

    def __init__(self, *, path: Path) -> None:
        """Open (and create if needed) the database at ``path``."""
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        migrate_legacy_nets(path=path)
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
