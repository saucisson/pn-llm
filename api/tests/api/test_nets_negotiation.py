import json

import pytest

from app.domain.canonical import net_id_of
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml
from tests.support import MUTEX_DOCUMENT, MUTEX_PNML

DOCUMENT_JSON = MUTEX_DOCUMENT.model_dump_json(exclude_none=True, exclude_defaults=True).encode()
EXPECTED_ID = net_id_of(document=MUTEX_DOCUMENT)


def post(client, *, body, content_type):
    headers = {} if content_type is None else {"Content-Type": content_type}
    return client.post("/v1/nets", content=body, headers=headers)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (DOCUMENT_JSON, "application/json"),
        (DOCUMENT_JSON, None),
        (DOCUMENT_JSON, "application/json; charset=utf-8"),
        (MUTEX_PNML, "application/pnml+xml"),
        (MUTEX_PNML, "application/xml"),
        (MUTEX_PNML, "text/xml"),
    ],
)
def test_every_accepted_upload_gives_the_same_id(client, body, content_type):
    response = post(client, body=body, content_type=content_type)
    assert response.status_code in {200, 201}
    assert response.json()["net_id"] == EXPECTED_ID
    assert response.headers["location"] == f"/v1/nets/{EXPECTED_ID}"


def test_first_upload_is_201_and_the_next_is_200(client):
    assert post(client, body=MUTEX_PNML, content_type="text/xml").status_code == 201
    again = post(client, body=DOCUMENT_JSON, content_type="application/json")
    assert again.status_code == 200
    assert again.json()["created"] is False


def test_unsupported_content_type_is_415(client):
    response = post(client, body=b"x", content_type="text/plain")
    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/problem+json")


def test_invalid_json_is_422_with_a_pointer(client):
    body = json.dumps({"source_id": "n", "type_uri": "u", "places": [{"id": 3}]}).encode()
    response = post(client, body=body, content_type="application/json")
    assert response.status_code == 422
    assert response.json()["location"] == "/places/0/id"


def test_get_defaults_to_json_with_cache_headers(client):
    post(client, body=MUTEX_PNML, content_type="application/xml")
    response = client.get(f"/v1/nets/{EXPECTED_ID}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["etag"] == f'"{EXPECTED_ID}"'
    assert "immutable" in response.headers["cache-control"]
    assert response.headers["vary"] == "Accept"
    assert response.json()["schema_version"] == "1.0"
    assert net_id_of(document=type(MUTEX_DOCUMENT).model_validate(response.json())) == EXPECTED_ID


def test_get_with_accept_pnml_returns_canonical_pnml_that_reimports_identically(client):
    post(client, body=DOCUMENT_JSON, content_type="application/json")
    response = client.get(f"/v1/nets/{EXPECTED_ID}", headers={"Accept": "application/pnml+xml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pnml+xml")
    assert response.headers["etag"] == f'"{EXPECTED_ID}"'
    reimported = import_pnml(payload=response.content, limits=DocumentLimits())
    assert net_id_of(document=reimported) == EXPECTED_ID


def test_get_with_an_unacceptable_type_is_406(client):
    post(client, body=MUTEX_PNML, content_type="application/xml")
    response = client.get(f"/v1/nets/{EXPECTED_ID}", headers={"Accept": "text/html"})
    assert response.status_code == 406
    assert response.headers["content-type"].startswith("application/problem+json")


def test_get_of_an_unknown_net_is_404_whatever_the_accept(client):
    assert (
        client.get("/v1/nets/nope", headers={"Accept": "application/pnml+xml"}).status_code == 404
    )
