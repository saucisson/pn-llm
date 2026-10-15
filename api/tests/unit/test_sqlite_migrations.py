import sqlite3
import threading

import pytest

from app.infrastructure.sqlite_migrations import (
    LATEST_VERSION,
    MIGRATIONS,
    StoreMigrationError,
    migrate,
)
from app.infrastructure.sqlite_store import SqliteStore


def version_of(path):
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


def tables_of(path):
    rows = sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in rows}


def test_migrations_are_numbered_without_gaps_from_one():
    assert [m.version for m in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))
    assert len(MIGRATIONS) == LATEST_VERSION


def test_a_new_database_is_created_at_the_latest_version(tmp_path):
    path = tmp_path / "new.sqlite"
    assert migrate(path=path) == LATEST_VERSION
    assert version_of(path) == LATEST_VERSION
    assert {"nets", "jobs", "traces"} <= tables_of(path)


def test_migrating_twice_changes_nothing(tmp_path):
    path = tmp_path / "db.sqlite"
    SqliteStore(path=path)
    SqliteStore(path=path)
    assert version_of(path) == LATEST_VERSION


def test_a_database_from_before_versioning_gets_a_version_and_what_it_lacked(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE nets (net_id TEXT PRIMARY KEY, summary TEXT NOT NULL,
               document BLOB NOT NULL, created_at REAL NOT NULL);
           CREATE TABLE jobs (job_id TEXT PRIMARY KEY, net_id TEXT NOT NULL, job_key TEXT NOT NULL,
               state TEXT NOT NULL, request TEXT NOT NULL, results TEXT NOT NULL DEFAULT '[]',
               lease_expires_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
           INSERT INTO nets VALUES ('n', '{}', x'00', 1.0);"""
    )
    conn.commit()
    conn.close()
    assert "traces" not in tables_of(path)

    migrate(path=path)

    assert version_of(path) == LATEST_VERSION
    assert "traces" in tables_of(path)
    assert sqlite3.connect(path).execute("SELECT net_id FROM nets").fetchall() == [("n",)]


def test_a_database_from_a_newer_version_is_refused_untouched(tmp_path):
    path = tmp_path / "future.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(StoreMigrationError, match="newer"):
        migrate(path=path)
    assert version_of(path) == LATEST_VERSION + 1
    assert tables_of(path) == set()


@pytest.mark.parametrize("round_number", range(30))
def test_several_processes_starting_together_migrate_once(tmp_path, round_number):
    """Without the retry on the switch to WAL, about one start in six failed with 'locked'."""
    path = tmp_path / f"race{round_number}.sqlite"
    errors = []

    def start():
        try:
            migrate(path=path)
        except Exception as exc:  # noqa: BLE001 - collected to fail the test with the cause
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert version_of(path) == LATEST_VERSION
