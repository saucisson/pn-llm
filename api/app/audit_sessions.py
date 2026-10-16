"""Audit the stored sessions (``python -m app.audit_sessions [--session ID ...]``).

Fails (exit 1) when a verdict in a session log has no engine result behind it, and lists the
contradictions between engines found in the jobs the sessions used. Measure M1 of the protocol.
"""

from __future__ import annotations

import argparse
import sys

from app.application.soundness import SoundnessAuditor
from app.infrastructure.sqlite_store import SqliteStore
from app.settings import Settings


def audit_main() -> None:
    """Audit, print the report as JSON and exit 1 when a verdict is unsupported."""
    parser = argparse.ArgumentParser(description="Audit session logs against engine results.")
    parser.add_argument("--session", action="append", help="a session id; all when omitted")
    arguments = parser.parse_args()
    store = SqliteStore(path=Settings().database_path)
    report = SoundnessAuditor(sessions=store, jobs=store).audit(
        session_ids=None if arguments.session is None else tuple(arguments.session)
    )
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    sys.exit(0 if report.sound else 1)


if __name__ == "__main__":
    audit_main()
