import pytest
from fastapi.testclient import TestClient

from app.domain.descriptions import description_id_of
from app.main import create_app
from app.settings import Settings
from tests.support import MUTEX_PNML

XML = {"Content-Type": "application/pnml+xml"}
TEXT = {"Content-Type": "text/plain; charset=utf-8"}


@pytest.fixture
def net_id(client):
    return client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]


def add(client, net_id, text, *, headers=TEXT, **params):
    body = text if isinstance(text, bytes) else text.encode()
    return client.post(
        f"/v1/nets/{net_id}/descriptions", content=body, headers=headers, params=params
    )


def test_adding_a_description_returns_it_with_its_hash_and_origin(client, net_id):
    response = add(client, net_id, "Two processes share a lock.")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["description_id"] == description_id_of(text="Two processes share a lock.")
    assert data["origin"] == "user"
    assert data["net_id"] == net_id
    assert data["text"] == "Two processes share a lock."
    assert response.headers["location"] == f"/v1/descriptions/{data['description_id']}"


def test_the_same_text_twice_is_idempotent(client, net_id):
    first = add(client, net_id, "same")
    second = add(client, net_id, "same")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["data"] == second.json()["data"]
    assert len(client.get(f"/v1/nets/{net_id}/descriptions").json()["data"]) == 1


def test_text_is_stored_exactly_as_sent(client, net_id):
    text = "  Café → é \n\n  lock  \t"
    description_id = add(client, net_id, text).json()["data"]["description_id"]
    stored = client.get(f"/v1/descriptions/{description_id}").json()["data"][0]["text"]
    assert stored == text


def test_a_net_can_have_several_descriptions_with_their_origins(client, net_id):
    add(client, net_id, "by the user")
    add(client, net_id, "by the assistant", origin="llm", headers={"Content-Type": "text/markdown"})
    listed = client.get(f"/v1/nets/{net_id}/descriptions").json()["data"]
    assert [(d["text"], d["origin"]) for d in listed] == [
        ("by the user", "user"),
        ("by the assistant", "llm"),
    ]


def test_the_same_text_can_describe_two_nets_and_two_origins(client, net_id):
    other = client.post(
        "/v1/nets", content=MUTEX_PNML.replace(b'id="mutex"', b'id="other"'), headers=XML
    ).json()["net_id"]
    one = add(client, net_id, "shared text").json()["data"]["description_id"]
    two = add(client, other, "shared text").json()["data"]["description_id"]
    add(client, net_id, "shared text", origin="mcc")
    assert one == two
    links = client.get(f"/v1/descriptions/{one}").json()["data"]
    assert {(link["net_id"], link["origin"]) for link in links} == {
        (net_id, "user"),
        (other, "user"),
        (net_id, "mcc"),
    }


def test_unknown_net_and_description_are_404(client, net_id):
    assert add(client, "nope", "x").status_code == 404
    assert client.get("/v1/nets/nope/descriptions").status_code == 404
    assert client.get("/v1/descriptions/nope").status_code == 404


def test_an_oversized_description_is_a_413(tmp_path):
    settings = Settings(database_path=tmp_path / "d.sqlite", max_description_bytes=10)
    small = TestClient(create_app(settings=settings))
    net_id = small.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    assert add(small, net_id, "x" * 11).status_code == 413
    assert add(small, net_id, "x" * 10).status_code == 201


@pytest.mark.parametrize(
    ("body", "headers", "status"),
    [
        (b"", TEXT, 422),
        (b"   \n", TEXT, 422),
        (b"\xff\xfe\x00", TEXT, 422),
        (b"<x/>", {"Content-Type": "application/xml"}, 415),
        (b"{}", {"Content-Type": "application/json"}, 415),
    ],
)
def test_bad_bodies_are_refused(client, net_id, body, headers, status):
    assert add(client, net_id, body, headers=headers).status_code == status


def test_an_unknown_origin_is_a_422(client, net_id):
    assert add(client, net_id, "x", origin="oracle").status_code == 422
