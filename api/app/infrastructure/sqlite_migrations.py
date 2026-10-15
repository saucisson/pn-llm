"""Versioned schema of the SQLite database, applied at start-up.

The schema version is ``PRAGMA user_version``. Migrations are numbered, applied in order inside
one transaction taken with ``BEGIN IMMEDIATE`` (so several processes starting together cannot
apply one twice: the second finds the work done), and never edited once released: a change to the
schema is a new migration. A database written by a newer version of the software is refused
rather than damaged. Before versioning existed, databases were recognised by their tables.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import zlib
from pathlib import Path

from app.domain.canonical import canonical_bytes, net_id_of
from app.domain.errors import InvalidNetError
from app.domain.models import DomainModel
from app.domain.net_validation import DocumentLimits
from app.domain.nets import summarize_document
from app.domain.pnml_import import import_pnml


class StoreMigrationError(Exception):
    """Stored data cannot be migrated to the current schema; the database was left unchanged."""


class Migration(DomainModel):
    """One numbered step of the schema: its statements run in order, in one transaction."""

    version: int
    description: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        description="nets, jobs and traces",
        statements=(
            """CREATE TABLE IF NOT EXISTS nets (
    net_id     TEXT PRIMARY KEY,
    summary    TEXT NOT NULL,          -- NetSummary as JSON
    document   BLOB NOT NULL,          -- canonical NetDocument JSON, zlib-compressed, immutable
    created_at REAL NOT NULL
)""",
            """CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    net_id     TEXT NOT NULL REFERENCES nets(net_id),
    job_key    TEXT NOT NULL,          -- idempotency key: hash(net_id, request)
    state      TEXT NOT NULL,
    request    TEXT NOT NULL,          -- CheckRequest as JSON
    results    TEXT NOT NULL DEFAULT '[]',
    lease_expires_at REAL NOT NULL,    -- a live job whose lease expired belongs to a dead process
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)""",
            "CREATE INDEX IF NOT EXISTS jobs_net ON jobs(net_id)",
            """CREATE TABLE IF NOT EXISTS traces (
    job_id     TEXT NOT NULL REFERENCES jobs(job_id),
    formula_id TEXT NOT NULL,
    trace      BLOB NOT NULL,          -- Trace as JSON, zlib-compressed
    PRIMARY KEY (job_id, formula_id)
)""",
            # At most one live job per idempotency key, even under concurrent submissions.
            """CREATE UNIQUE INDEX IF NOT EXISTS jobs_live_key ON jobs(job_key)
    WHERE state IN ('queued', 'running', 'done')""",
        ),
    ),
    Migration(
        version=2,
        description="index for the retention of finished jobs and for claiming queued jobs",
        statements=("CREATE INDEX IF NOT EXISTS jobs_state_updated ON jobs(state, updated_at)",),
    ),
    Migration(
        version=3,
        description="net descriptions and their links to nets",
        statements=(
            """CREATE TABLE descriptions (
    description_id TEXT PRIMARY KEY,
    text           TEXT NOT NULL,      -- exactly as sent, UTF-8
    created_at     REAL NOT NULL
)""",
            """CREATE TABLE net_descriptions (
    net_id         TEXT NOT NULL REFERENCES nets(net_id),
    description_id TEXT NOT NULL REFERENCES descriptions(description_id),
    origin         TEXT NOT NULL,      -- user, mcc or llm
    created_at     REAL NOT NULL,
    PRIMARY KEY (net_id, description_id, origin)
)""",
        ),
    ),
    Migration(
        version=4,
        description="sessions and their events",
        statements=(
            """CREATE TABLE sessions (
    session_id     TEXT PRIMARY KEY,
    net_id         TEXT NOT NULL REFERENCES nets(net_id),
    description_id TEXT REFERENCES descriptions(description_id),
    state          TEXT NOT NULL,
    lease_expires_at REAL NOT NULL DEFAULT 0,  -- meaningful while the session is running
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
)""",
            "CREATE INDEX sessions_state ON sessions(state, created_at)",
            """CREATE TABLE events (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    number     INTEGER NOT NULL,
    at         REAL NOT NULL,
    kind       TEXT NOT NULL,
    body       TEXT NOT NULL,          -- the SessionEvent as JSON
    PRIMARY KEY (session_id, number)
)""",
        ),
    ),
    Migration(
        version=5,
        description="contest families and the stored nets that are their instances",
        statements=(
            """CREATE TABLE mcc_families (
    name         TEXT PRIMARY KEY,
    family       TEXT NOT NULL          -- the MccFamily as JSON
)""",
            """CREATE TABLE mcc_nets (
    family   TEXT NOT NULL REFERENCES mcc_families(name),
    instance TEXT NOT NULL,
    net_type TEXT NOT NULL,
    net_id   TEXT NOT NULL REFERENCES nets(net_id),
    member   TEXT NOT NULL,            -- path inside the family archive
    PRIMARY KEY (family, instance, net_type)
)""",
            "CREATE INDEX mcc_nets_net ON mcc_nets(net_id)",
        ),
    ),
    Migration(
        version=6,
        description="the contest's properties of each net, per examination",
        statements=(
            """CREATE TABLE mcc_properties (
    net_id      TEXT NOT NULL REFERENCES nets(net_id),
    examination TEXT NOT NULL,
    body        BLOB NOT NULL,         -- MccProperties as JSON, zlib-compressed
    PRIMARY KEY (net_id, examination)
)""",
        ),
    ),
    Migration(
        version=7,
        description="the contest's published runs, with the provenance of each result set",
        statements=(
            """CREATE TABLE mcc_result_sets (
    year   INTEGER PRIMARY KEY,
    url    TEXT NOT NULL,
    sha256 TEXT NOT NULL,              -- of the downloaded archive
    runs   INTEGER NOT NULL
)""",
            """CREATE TABLE mcc_runs (
    year          INTEGER NOT NULL REFERENCES mcc_result_sets(year),
    run_id        TEXT NOT NULL,
    tool          TEXT NOT NULL,       -- normalized: lower case, no year
    reference     INTEGER NOT NULL,    -- 1 for a virtual or past-winner reference, not an engine
    instance      TEXT NOT NULL,
    family        TEXT NOT NULL,
    net_type      TEXT,
    examination   TEXT NOT NULL,
    cores         INTEGER NOT NULL,
    outcome       TEXT NOT NULL,       -- computed, did_not_compute, did_not_finish, cannot_compute
    results       TEXT NOT NULL,       -- the contest's answer string; empty unless computed
    techniques    TEXT NOT NULL,       -- space separated
    memory_mb     REAL NOT NULL,
    cpu_ms        REAL NOT NULL,
    time_ms       REAL NOT NULL,
    timed_out     INTEGER NOT NULL,
    out_of_memory INTEGER NOT NULL      -- run_id is not unique: the file repeats some runs
)""",
            "CREATE INDEX mcc_runs_lookup ON mcc_runs(tool, examination, family)",
        ),
    ),
    Migration(
        version=8,
        description="frozen splits of the families into folds and a held-out test set",
        statements=(
            """CREATE TABLE mcc_splits (
    name       TEXT PRIMARY KEY,
    body       TEXT NOT NULL,          -- the Split as JSON; never updated
    created_at REAL NOT NULL
)""",
        ),
    ),
    Migration(
        version=9,
        description="runs of operations (analyses and reductions) and their cached results",
        statements=(
            """CREATE TABLE operation_runs (
    run_id           TEXT PRIMARY KEY,
    net_id           TEXT NOT NULL REFERENCES nets(net_id),
    operation        TEXT NOT NULL,
    engine           TEXT NOT NULL,
    tool_version     TEXT NOT NULL,
    run_key          TEXT NOT NULL,    -- hash(net, operation, parameters, engine, tool version)
    parameters       TEXT NOT NULL,    -- JSON
    limits           TEXT NOT NULL,    -- JSON
    state            TEXT NOT NULL,
    outcome          TEXT,             -- the OperationOutcome as JSON, once finished
    lease_expires_at REAL NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL
)""",
            "CREATE INDEX operation_runs_net ON operation_runs(net_id)",
            "CREATE INDEX operation_runs_state ON operation_runs(state, created_at)",
            # One live or finished run per key, even under concurrent submissions: that run is
            # the cache of the operation.
            """CREATE UNIQUE INDEX operation_runs_live_key ON operation_runs(run_key)
    WHERE state IN ('queued', 'running', 'done')""",
        ),
    ),
    Migration(
        version=10,
        description="how a net was derived from another by a reduction",
        statements=(
            """CREATE TABLE net_lineage (
    net_id     TEXT NOT NULL REFERENCES nets(net_id),
    parent_id  TEXT NOT NULL REFERENCES nets(net_id),
    rule       TEXT NOT NULL,
    lineage    TEXT NOT NULL,          -- the Lineage as JSON (what each transition stands for)
    PRIMARY KEY (net_id, parent_id, rule)
)""",
            "CREATE INDEX net_lineage_parent ON net_lineage(parent_id)",
        ),
    ),
)
LATEST_VERSION = MIGRATIONS[-1].version
WAL_ATTEMPTS = 50
WAL_RETRY_DELAY_S = 0.1


def convert_legacy_nets(*, conn: sqlite3.Connection) -> None:
    """Re-import the nets of a first-schema database as canonical documents.

    The first schema kept the uploaded PNML bytes under a hash of the file. Each net is imported
    again, gets its canonical id, and the jobs that point to it follow. All or nothing: a net that
    no longer imports (the rules are stricter now) aborts the migration. Migrated jobs get a fresh
    idempotency key, so two nets that collapse into one cannot collide. The caller owns the
    transaction and has switched foreign keys off.

    Raises:
        StoreMigrationError: if a stored net cannot be imported.
    """
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
            key = hashlib.sha256(f"{new_id}|{job['request']}|{job['job_id']}".encode()).hexdigest()
            conn.execute(
                "UPDATE jobs SET net_id=?, job_key=? WHERE job_id=?",
                (new_id, key, job["job_id"]),
            )
    conn.execute("DROP TABLE nets")
    conn.execute("ALTER TABLE nets_new RENAME TO nets")


def migrate(*, path: Path) -> int:
    """Bring the database at ``path`` to the latest schema; return the version it is at.

    A database without version is recognised by its tables: none means a new one, a ``pnml``
    column means the first schema (nets are converted), anything else is the unversioned current
    schema. Missing objects of version 1 are created either way.

    Raises:
        StoreMigrationError: if a stored net cannot be converted, or the database comes from a
            newer version of the software.
    """
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        # Switching to WAL needs an exclusive lock and SQLite may refuse at once, whatever the
        # timeout, when processes start together: retry, the winner leaves the file in WAL.
        for attempt in range(WAL_ATTEMPTS):
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError:
                if attempt == WAL_ATTEMPTS - 1:
                    raise
                time.sleep(WAL_RETRY_DELAY_S)
        conn.execute("PRAGMA foreign_keys=OFF")  # table swaps below must not be refused
        conn.execute("BEGIN IMMEDIATE")  # another process may be migrating: look inside the lock
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > LATEST_VERSION:
            message = (
                f"The database is at schema version {version}, newer than this software "
                f"({LATEST_VERSION}): refusing to open it"
            )
            raise StoreMigrationError(message)
        if (
            version == 0
            and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nets'"
            ).fetchone()
        ):
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(nets)")}
            if "pnml" in columns:
                convert_legacy_nets(conn=conn)
            version = 0  # version 1 creates whatever the old schema lacked, IF NOT EXISTS
        for migration in MIGRATIONS:
            if migration.version <= version:
                continue
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {migration.version}")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return LATEST_VERSION
