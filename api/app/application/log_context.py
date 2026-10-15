"""Context shared by the log lines of one request: set by the API, read by the log formatter."""

from __future__ import annotations

from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="")
