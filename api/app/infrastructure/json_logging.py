"""Structured logs: one JSON object per line, with the fields that make a run traceable.

Lines carry the time, level, logger, message, the request id of the request being served and
whatever fields the caller attached (job id, net id, engine, duration...). Nothing here ever
formats a net or a payload: callers log identifiers and measures only.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.application.log_context import request_id

HANDLER_NAME = "pnverif"

# Attributes every LogRecord has: anything else was attached by the caller with ``extra=``.
STANDARD_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Format a log record as one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: PLR0917 - imposed by logging
        """Return the record as JSON text."""
        line: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        current = request_id.get()
        if current:
            line["request_id"] = current
        for key, value in record.__dict__.items():
            if key not in STANDARD_ATTRIBUTES:
                line[key] = value
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(*, level: str, as_json: bool) -> None:
    """Send the logs of the platform (and uvicorn's) to standard error, as JSON or plain text."""
    handler = logging.StreamHandler()
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(
        JsonFormatter()
        if as_json
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    # Replace our own handler only: others (a test's capture, an embedding application) stay.
    for existing in root.handlers[:]:
        if existing.get_name() == HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
