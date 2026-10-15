"""Frozen splits of the families in the SQLite database."""

from __future__ import annotations

import sqlite3
import time

from app.domain.errors import ConflictError, NotFoundError
from app.domain.splits import Split

from .sqlite_database import SqliteDatabase


class SqliteSplits(SqliteDatabase):
    """Implements the ``SplitRepository`` port."""

    def save_split(self, *, split: Split) -> None:
        """Store a split under its name, or raise ConflictError if the name is taken."""
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO mcc_splits(name, body, created_at) VALUES (?, ?, ?)",
                    (split.name, split.model_dump_json(), time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Split {split.name!r} exists and splits are frozen") from exc

    def load_split(self, *, name: str) -> Split:
        """Return a split, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute("SELECT body FROM mcc_splits WHERE name=?", (name,)).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown split {name!r}")
        return Split.model_validate_json(row["body"])

    def split_names(self) -> tuple[str, ...]:
        """Return the names of the stored splits."""
        with self._connection() as conn:
            rows = conn.execute("SELECT name FROM mcc_splits ORDER BY name").fetchall()
        return tuple(row["name"] for row in rows)
