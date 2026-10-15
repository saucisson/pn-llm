import threading

import pytest
from fastapi.testclient import TestClient

from app.domain.analyses import OPERATIONS
from app.main import create_app
from tests.support import MUTEX_PNML, InProcessNative

XML = {"Content-Type": "application/pnml+xml"}

# A net and parameters for each operation, and a fact its answer must contain: the contract test
# below fails for an operation added without a known answer.
KNOWN_ANSWERS = {
    "net-class": ({}, lambda data: data["marked_graph"] is True and data["state_machine"] is False),
    "p-invariants": ({}, lambda data: data["total"] == 2 and data["complete"] is True),
    "t-invariants": ({}, lambda data: data["total"] == 1 and data["uncovered_transitions"] == []),
    "place-bounds": ({}, lambda data: data["finite"] == 3 and data["complete"] is True),
    "minimal-siphons": ({}, lambda data: data["total"] == 2 and data["complete"] is True),
    "minimal-traps": ({}, lambda data: data["total"] == 2 and data["complete"] is True),
    "dead-transitions": ({}, lambda data: data["dead_transitions"] == []),
    "conflict-sets": ({}, lambda data: data["total"] == 0),
    "connected-components": ({}, lambda data: data["total"] == 1),
}


@pytest.fixture
def engines():
    return InProcessNative()


@pytest.fixture
def client(settings, engines):
    app = create_app(
        settings=settings.model_copy(update={"operation_wait_seconds": 0}), engine_gateway=engines
    )
    return TestClient(app)


@pytest.fixture
def net_id(client):
    return client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]


def ask(client, net_id, name, body=None):
    return client.post(f"/v1/nets/{net_id}/analyses/{name}", json=body or {"parameters": {}})


def test_every_operation_has_a_route_models_and_a_known_answer(client, net_id):
    paths = client.app.openapi()["paths"]
    catalog = {e["name"]: e for e in client.get("/v1/operations").json()["data"]}
    for definition in OPERATIONS:
        route = definition.route
        assert route in paths, definition.name
        assert catalog[definition.name]["route"] == route
        assert catalog[definition.name]["result_schema"]["type"] == "object"
        assert definition.name in KNOWN_ANSWERS, f"no known answer for {definition.name}"
    assert set(catalog) == {d.name for d in OPERATIONS}


@pytest.mark.parametrize("name", sorted(KNOWN_ANSWERS))
def test_the_known_answer_comes_back_in_the_envelope(client, net_id, name):
    parameters, holds = KNOWN_ANSWERS[name]
    queued = ask(client, net_id, name, {"parameters": parameters})
    assert queued.status_code == 202  # nobody has run it yet: the test client starts no worker
    client.app.state.operations.drain()
    answered = ask(client, net_id, name, {"parameters": parameters})
    assert answered.status_code == 200
    envelope = answered.json()
    assert envelope["status"] == "ok"
    assert envelope["tool"] == {"name": "native", "version": "1.0"}
    assert envelope["net_id"] == net_id
    assert holds(envelope["data"])


def test_a_slow_operation_gets_a_202_and_a_run_to_follow(client, net_id, engines):
    gate = threading.Event()
    engines.gate = gate
    first = ask(client, net_id, "p-invariants")
    assert first.status_code == 202
    handle = first.json()["data"]
    assert first.headers["Location"] == handle["location"] == f"/v1/runs/{handle['run_id']}"
    worker = threading.Thread(target=client.app.state.operations.run_next)
    worker.start()
    running = client.get(handle["location"]).json()["data"]
    assert running["state"] in {"queued", "running"}
    assert running["result"] is None
    gate.set()
    worker.join()
    finished = client.get(handle["location"]).json()["data"]
    assert finished["state"] == "done"
    assert finished["result"]["total"] == 2


def test_the_request_waits_for_a_quick_operation(settings):
    app = create_app(
        settings=settings.model_copy(update={"operation_wait_seconds": 10, "embedded_workers": 1}),
        engine_gateway=InProcessNative(),
    )
    with TestClient(app) as client:
        net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
        response = ask(client, net_id, "net-class")
    assert response.status_code == 200
    assert response.json()["data"]["ordinary"] is True


def test_a_run_can_be_cancelled_through_the_api(client, net_id):
    handle = ask(client, net_id, "net-class").json()["data"]
    assert client.delete(f"/v1/runs/{handle['run_id']}").status_code == 204
    state = client.get(f"/v1/runs/{handle['run_id']}").json()["data"]["state"]
    assert state == "cancelled"
    assert client.delete("/v1/runs/nope").status_code == 404
    assert client.get("/v1/runs/nope").status_code == 404


def test_a_cancelled_run_asked_again_is_a_failed_envelope_not_an_error(client, net_id):
    engines = client.app.state.operations._engines
    handle = ask(client, net_id, "net-class").json()["data"]
    client.delete(f"/v1/runs/{handle['run_id']}")
    operations = client.app.state.operations
    run = operations.get(run_id=handle["run_id"])
    from app.api.operations import envelope_of
    from app.domain.analyses import find_operation

    envelope = envelope_of(run=run, definition=find_operation(name="net-class"), started=0.0)
    assert envelope.status == "failed"
    assert envelope.error.code == "cancelled"
    assert engines is not None


def test_errors_are_problems(client, net_id):
    assert ask(client, "nope", "net-class").status_code == 404
    unknown_engine = ask(client, net_id, "net-class", {"engine": "tapaal", "parameters": {}})
    assert unknown_engine.status_code == 422
    assert client.post(f"/v1/nets/{net_id}/analyses/nope", json={}).status_code == 404
    too_big = ask(client, net_id, "p-invariants", {"parameters": {"max_rows": 0}})
    assert too_big.status_code == 422
    assert ask(client, net_id, "net-class", {"parameters": {"unexpected": 1}}).status_code in {
        200,
        202,
        422,
    }


def test_a_failed_run_is_reported_in_the_envelope_and_on_the_run(settings):
    def lie(report):
        return report.model_copy(update={"result": {"nonsense": True}})

    app = create_app(
        settings=settings.model_copy(update={"operation_wait_seconds": 10, "embedded_workers": 1}),
        engine_gateway=InProcessNative(tamper=lie),
    )
    with TestClient(app) as client:
        net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
        response = ask(client, net_id, "net-class")
        assert response.status_code == 200
        envelope = response.json()
        assert (envelope["status"], envelope["error"]["code"], envelope["data"]) == (
            "failed",
            "invalid_result",
            None,
        )
        runs = app.state.operations
        failed = [
            r
            for r in (runs.get(run_id=i) for i in _run_ids(settings))
            if r.operation == "net-class"
        ]
        view = client.get(f"/v1/runs/{failed[0].run_id}").json()["data"]
        assert (view["state"], view["error"]["code"]) == ("failed", "invalid_result")


def _run_ids(settings):
    from tests.support import query

    return [
        row[0]
        for row in query(path=settings.database_path, sql="SELECT run_id FROM operation_runs")
    ]
