"""Backup and restore of the SQLite database (docs/architecture.md, "Backups").

A backup uses SQLite's online backup API: it is consistent even while the API is running and
writing. A restore replaces the database file and must be done with every API process stopped.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from .sqlite_migrations import LATEST_VERSION, StoreMigrationError


def backup_database(*, source: Path, target: Path) -> None:
    """Copy the database at ``source`` to a new file ``target``, consistently.

    Raises:
        FileExistsError: if ``target`` exists: a backup never overwrites another one.
    """
    if target.exists():
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    origin = sqlite3.connect(source, timeout=30)
    copy = sqlite3.connect(target)
    try:
        origin.backup(copy)
    finally:
        copy.close()
        origin.close()


def restore_database(*, backup: Path, target: Path) -> None:
    """Replace the database at ``target`` with ``backup`` after checking the backup is sound.

    The write-ahead files of the old database are removed, or SQLite would replay them over the
    restored data. Every process using ``target`` must be stopped first.

    Raises:
        StoreMigrationError: if the backup is damaged or comes from a newer software version.
    """
    check = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        verdict = check.execute("PRAGMA integrity_check").fetchone()[0]
        version = int(check.execute("PRAGMA user_version").fetchone()[0])
    finally:
        check.close()
    if verdict != "ok":
        raise StoreMigrationError(f"The backup is damaged: {verdict}")
    if version > LATEST_VERSION:
        raise StoreMigrationError(f"The backup is at schema version {version}, too new")
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(backup, target)
