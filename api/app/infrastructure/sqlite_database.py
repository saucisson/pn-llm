"""What every SQLite adapter shares: the file, its migration, and short-lived connections."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from .sqlite_migrations import migrate


class SqliteDatabase:
    """The database file of the platform, opened one short-lived connection per operation."""

    def __init__(self, *, path: Path) -> None:
        """Open (and create or migrate if needed) the database at ``path``."""
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
