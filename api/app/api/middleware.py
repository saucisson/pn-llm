"""Request correlation and access log."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.application.log_context import request_id

logger = logging.getLogger("pnverif.http")

REQUEST_ID_HEADER = "X-Request-ID"
# An id sent by a client is kept only if it looks like one: it ends up in logs.
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
REQUEST_ID_LENGTH = 16


async def log_requests(  # noqa: PLR0917 - signature imposed by the framework
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Give the request an id, log it with its duration, and return the id in the response."""
    sent = request.headers.get(REQUEST_ID_HEADER, "")
    current = sent if SAFE_REQUEST_ID.match(sent) else uuid.uuid4().hex[:REQUEST_ID_LENGTH]
    token = request_id.set(current)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "request",
            extra={"method": request.method, "path": request.url.path, "duration_ms": duration_ms},
        )
        request_id.reset(token)
    response.headers[REQUEST_ID_HEADER] = current
    return response
