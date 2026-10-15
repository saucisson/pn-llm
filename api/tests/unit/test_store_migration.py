import sqlite3

import pytest

from app.domain.canonical import net_id_of
from app.infrastructure.sqlite_store import SqliteStore, StoreMigrationError
from tests.support import MUTEX_DOCUMENT, MUTEX_PNML, make_request

LEGACY_SCHEMA = """
CREATE TABLE nets (net_id TEXT PRIMARY KEY, summary TEXT NOT NULL, pnml BLOB NOT NULL,
                   created_at REAL NOT NULL);
CREATE TABLE jobs (job_id TEXT PRIMARY KEY, net_id TEXT NOT NULL REFERENCES nets(net_id),
                   job_key TEXT NOT NULL, state TEXT NOT NULL, request TEXT NOT NULL,
                   results TEXT NOT NULL DEFAULT '[]', lease_expires_at REAL NOT NULL,
                   created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE UNIQUE INDEX jobs_live_key ON jobs(job_key) WHERE state IN ('queued', 'running', 'done');
"""
REQUEST = make_request().model_dump_json()


def make_legacy_database(*, path, pnml_bytes):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO nets VALUES ('oldid', '{}', ?, 1.0)", (pnml_bytes,))
    conn.execute(
        "INSERT INTO jobs VALUES ('j1', 'oldid', 'k', 'done', ?, '[]', 0, 1.0, 1.0)", (REQUEST,)
    )
    conn.commit()
    conn.close()


def test_a_legacy_database_is_migrated_to_canonical_documents(tmp_path):
    path = tmp_path / "legacy.sqlite"
    make_legacy_database(path=path, pnml_bytes=MUTEX_PNML)

    store = SqliteStore(path=path)

    new_id = net_id_of(document=MUTEX_DOCUMENT)
    stored = store.load_net(net_id=new_id)
    assert stored.summary.places == 3
    assert store.load_job(job_id="j1").net_id == new_id
    with pytest.raises(Exception, match="Unknown net"):
        store.load_net(net_id="oldid")
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert "pnml" not in [row[1] for row in conn.execute("PRAGMA table_info(nets)")]


def test_migration_runs_once_and_a_second_open_changes_nothing(tmp_path):
    path = tmp_path / "legacy.sqlite"
    make_legacy_database(path=path, pnml_bytes=MUTEX_PNML)
    SqliteStore(path=path)
    again = SqliteStore(path=path)
    assert again.load_net(net_id=net_id_of(document=MUTEX_DOCUMENT)).summary.places == 3


def test_a_net_that_no_longer_imports_aborts_the_migration_untouched(tmp_path):
    path = tmp_path / "legacy.sqlite"
    make_legacy_database(path=path, pnml_bytes=b"<not xml")

    with pytest.raises(StoreMigrationError, match="oldid"):
        SqliteStore(path=path)

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT net_id FROM nets").fetchall() == [("oldid",)]
    assert conn.execute("SELECT net_id FROM jobs").fetchall() == [("oldid",)]


def test_a_new_database_needs_no_migration(tmp_path):
    SqliteStore(path=tmp_path / "fresh.sqlite")
