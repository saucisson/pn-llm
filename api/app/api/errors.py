"""Map domain errors to RFC 9457 problem responses (one place, one rule per error class)."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    DomainError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
)

# The first matching class wins, so list specific classes before general ones.
STATUS_BY_ERROR: tuple[tuple[type[DomainError], HTTPStatus], ...] = (
    (NotFoundError, HTTPStatus.NOT_FOUND),
    (PayloadTooLargeError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (InvalidRequestError, HTTPStatus.UNPROCESSABLE_ENTITY),
)


async def handle_domain_error(_: Request, exc: Exception) -> JSONResponse:  # noqa: PLR0917
    """Turn a domain error into a problem response; unmapped errors are a 500, never silent."""
    status = HTTPStatus.INTERNAL_SERVER_ERROR
    for error_type, mapped_status in STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            status = mapped_status
            break
    return JSONResponse(
        status_code=status.value,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": status.phrase,
            "status": status.value,
            "detail": str(exc),
        },
    )


def register_error_handlers(*, app: FastAPI) -> None:
    """Install the domain-error handler on ``app``."""
    app.add_exception_handler(DomainError, handle_domain_error)
