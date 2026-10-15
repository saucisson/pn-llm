"""Back up or restore the SQLite database.

    python3 scripts/db_backup.py backup data/pnverif.sqlite backups/2026-10-15.sqlite
    python3 scripts/db_backup.py restore backups/2026-10-15.sqlite data/pnverif.sqlite

A backup is safe while the API runs. Stop every API process before a restore.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from app.infrastructure.sqlite_backup import backup_database, restore_database  # noqa: E402  (needs the path above)

USAGE = __doc__
ARGUMENT_COUNT = 4


def main() -> int:
    """Run the requested operation; return the exit code."""
    if len(sys.argv) != ARGUMENT_COUNT or sys.argv[1] not in {"backup", "restore"}:
        print(USAGE)  # noqa: T201  (command-line output)
        return 2
    first, second = Path(sys.argv[2]), Path(sys.argv[3])
    if sys.argv[1] == "backup":
        backup_database(source=first, target=second)
    else:
        restore_database(backup=first, target=second)
    return 0


if __name__ == "__main__":
    sys.exit(main())
