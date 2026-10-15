import pytest
from fastapi.testclient import TestClient

from app.domain.llm import LlmStep
from app.infrastructure.scripted_llm import ScriptedLlm
from app.main import create_app
from app.settings import Settings
from tests.support import CHECK_BODY, MUTEX_PNML, ScriptedEngines

XML = {"Content-Type": "application/pnml+xml"}


@pytest.fixture
def client(tmp_path):
    config = Settings(database_path=tmp_path / "d.sqlite", embedded_workers=0)
    return TestClient(
        create_app(
            settings=config,
            engine_gateway=ScriptedEngines(),
            llm_gateway=ScriptedLlm(steps=(LlmStep(text="x"),)),
        )
    )


def test_deleting_a_session_removes_it_and_its_events(client):
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    assert client.delete(f"/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/v1/sessions/{sid}").status_code == 404
    assert client.get(f"/v1/sessions/{sid}/events").status_code == 404
    assert client.delete(f"/v1/sessions/{sid}").status_code == 404
    assert client.get(f"/v1/nets/{net_id}").status_code == 200  # the net is not the session's


def test_a_net_in_use_needs_cascade_and_goes_with_what_depends_on_it(client):
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    job_id = client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY).json()["data"]["job_id"]
    client.app.state.checks.drain()
    assert client.delete(f"/v1/nets/{net_id}").status_code == 409
    assert client.delete(f"/v1/nets/{net_id}?cascade=true").status_code == 204
    assert client.get(f"/v1/nets/{net_id}").status_code == 404
    assert client.get(f"/v1/jobs/{job_id}").status_code == 404
    assert client.delete(f"/v1/nets/{net_id}").status_code == 404


def test_a_net_with_a_queued_job_is_never_deleted(client):
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY)  # queued, not run
    assert client.delete(f"/v1/nets/{net_id}?cascade=true").status_code == 409


def test_a_description_is_unlinked_through_the_api(client):
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    description_id = client.post(
        f"/v1/nets/{net_id}/descriptions", content=b"text", headers={"Content-Type": "text/plain"}
    ).json()["data"]["description_id"]
    assert client.delete(f"/v1/descriptions/{description_id}").status_code == 422  # net_id needed
    assert client.delete(f"/v1/descriptions/{description_id}?net_id=nope").status_code == 404
    assert client.delete(f"/v1/descriptions/{description_id}?net_id={net_id}").status_code == 204
    assert client.get(f"/v1/descriptions/{description_id}").status_code == 404
    assert client.get(f"/v1/nets/{net_id}/descriptions").json()["data"] == []
