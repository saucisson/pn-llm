from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.domain.errors import (
    DomainError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
    PnmlError,
)
from app.main import create_app


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NotFoundError("x"), HTTPStatus.NOT_FOUND),
        (PayloadTooLargeError("x"), HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
        (InvalidRequestError("x"), HTTPStatus.UNPROCESSABLE_ENTITY),
        (PnmlError("x"), HTTPStatus.UNPROCESSABLE_ENTITY),  # a kind of invalid request
        (DomainError("x"), HTTPStatus.INTERNAL_SERVER_ERROR),  # unmapped: loud, never silent
    ],
)
def test_every_domain_error_has_a_status(settings, error, status):
    app = create_app(settings=settings)

    @app.get("/boom")
    def boom():
        raise error

    response = TestClient(app).get("/boom")
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == status.phrase
