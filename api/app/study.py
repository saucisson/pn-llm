"""Interaction measures of the user study (``python -m app.study [--session ID ...]``), M10.

Prints, for each session, what its log shows: time to the first definitive verdict, properties
proposed, questions asked, verdicts by kind. Usefulness and the reading of UNKNOWN and TIMEOUT
come from the participants (docs/user-study.md), not from here.
"""

from __future__ import annotations

import argparse
import sys

from pydantic import TypeAdapter

from app.application.session_log import read_events
from app.domain.study_measures import SessionMeasures, measure_session
from app.infrastructure.sqlite_store import SqliteStore
from app.settings import Settings


def study_main() -> None:
    """Measure the sessions asked for (all when none is named) and print them as JSON."""
    parser = argparse.ArgumentParser(description="Interaction measures of study sessions.")
    parser.add_argument("--session", action="append", help="a session id; all when omitted")
    arguments = parser.parse_args()
    store = SqliteStore(path=Settings().database_path)
    ids = tuple(arguments.session) if arguments.session else store.session_ids()
    measures = tuple(
        measure_session(session_id=i, events=read_events(sessions=store, session_id=i)) for i in ids
    )
    sys.stdout.write(
        TypeAdapter(tuple[SessionMeasures, ...]).dump_json(measures, indent=2).decode() + "\n"
    )


if __name__ == "__main__":
    study_main()
