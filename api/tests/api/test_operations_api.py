import threading

import pytest
from fastapi.testclient import TestClient

from app.domain.catalog import OPERATIONS
from app.domain.pnml_export import render_pnml
from app.domain.reductions.document import structure_to_document
from app.main import create_app
from tests.reduction_oracle import structure_of
from tests.support import MUTEX_PNML, InProcessNative

XML = {"Content-Type": "application/pnml+xml"}


# A net and parameters for each operation, and a fact its answer must contain: the contract test
# below fails for an operation added without a known answer.
def pnml_of(*, places, transitions, arcs, marking=None):
    """A net, as the PNML a user would upload."""
    structure = structure_of(places=places, transitions=transitions, arcs=arcs, marking=marking)
    return render_pnml(document=structure_to_document(structure=structure, source_id="n"))


TWIN_PLACES = pnml_of(
    places=["a", "b", "q"],
    transitions=["t", "u"],
    arcs=[("a", "t"), ("b", "t"), ("t", "q"), ("q", "u"), ("u", "a"), ("u", "b")],
    marking={"a": 1, "b": 1},
)
TWIN_TRANSITIONS = pnml_of(
    places=["p", "q"],
    transitions=["t", "t_copy"],
    arcs=[("p", "t"), ("t", "q"), ("p", "t_copy"), ("t_copy", "q")],
    marking={"p": 1},
)
SELF_LOOP = pnml_of(
    places=["p", "q"],
    transitions=["move", "noop"],
    arcs=[("p", "move"), ("move", "q"), ("q", "noop"), ("noop", "q")],
    marking={"p": 1},
)
DEAD = pnml_of(
    places=["p", "never", "out"],
    transitions=["live", "dead"],
    arcs=[("p", "live"), ("live", "p"), ("never", "dead"), ("dead", "out")],
    marking={"p": 1},
)
CHAIN = pnml_of(
    places=["a", "mid", "q"],
    transitions=["x", "t", "y"],
    arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("t", "q"), ("q", "y"), ("y", "a")],
    marking={"a": 1},
)
SINKS = pnml_of(
    places=["p", "q", "s"],
    transitions=["t"],
    arcs=[("p", "t"), ("t", "q"), ("t", "s")],
    marking={"p": 1},
)
# operation -> (net, parameters, what its answer must say)
KNOWN_ANSWERS = {
    "net-class": (
        MUTEX_PNML,
        {},
        lambda d: d["marked_graph"] is True and d["state_machine"] is False,
    ),
    "p-invariants": (MUTEX_PNML, {}, lambda d: d["total"] == 2 and d["complete"] is True),
    "t-invariants": (
        MUTEX_PNML,
        {},
        lambda d: d["total"] == 1 and d["uncovered_transitions"] == [],
    ),
    "place-bounds": (MUTEX_PNML, {}, lambda d: d["finite"] == 3 and d["complete"] is True),
    "minimal-siphons": (MUTEX_PNML, {}, lambda d: d["total"] == 2 and d["complete"] is True),
    "minimal-traps": (MUTEX_PNML, {}, lambda d: d["total"] == 2 and d["complete"] is True),
    "dead-transitions": (MUTEX_PNML, {}, lambda d: d["dead_transitions"] == []),
    "conflict-sets": (MUTEX_PNML, {}, lambda d: d["total"] == 0),
    "connected-components": (MUTEX_PNML, {}, lambda d: d["total"] == 1),
    "fuse-parallel-places": (TWIN_PLACES, {}, lambda d: [r["id"] for r in d["removed"]] == ["b"]),
    "fuse-parallel-transitions": (
        TWIN_TRANSITIONS,
        {},
        lambda d: [r["id"] for r in d["removed"]] == ["t_copy"],
    ),
    "remove-self-loop-transitions": (
        SELF_LOOP,
        {},
        lambda d: [r["id"] for r in d["removed"]] == ["noop"],
    ),
    "remove-dead-transitions": (DEAD, {}, lambda d: [r["id"] for r in d["removed"]] == ["dead"]),
    "fuse-series-places": (
        CHAIN,
        {"max_applications": 1},
        lambda d: (
            [r["id"] for r in d["removed"]] == ["mid", "t"]
            and [e["original"][1]["id"] for e in d["expansions"]] == ["t"]
        ),
    ),
    "fuse-series-transitions": (
        CHAIN,
        {"max_applications": 1},
        lambda d: [r["id"] for r in d["removed"]] == ["mid", "t"],
    ),
    "remove-implicit-places": (SINKS, {}, lambda d: [r["id"] for r in d["removed"]] == ["q", "s"]),
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
    definition = next(d for d in OPERATIONS if d.name == name)
    return client.post(definition.route.format(net_id=net_id), json=body or {"parameters": {}})


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
def test_the_known_answer_comes_back_in_the_envelope(client, name):
    pnml, parameters, holds = KNOWN_ANSWERS[name]
    net_id = client.post("/v1/nets", content=pnml, headers=XML).json()["net_id"]
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
    from app.domain.catalog import find_operation

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


# ---- reductions create nets --------------------------------------------------------------------


def reduce_through_the_api(client, net_id, rule, body=None):
    asked = ask(client, net_id, rule, body or {"parameters": {}})
    client.app.state.operations.drain()
    return ask(client, net_id, rule, body or {"parameters": {}}), asked


def test_a_reduction_that_applies_stores_a_new_net_linked_to_its_parent(client, settings):
    parent = client.post("/v1/nets", content=TWIN_PLACES, headers=XML).json()["net_id"]
    answered, _ = reduce_through_the_api(client, parent, "fuse-parallel-places")
    data = answered.json()["data"]
    assert (data["changed"], data["parent_id"]) == (True, parent)
    child = data["new_net_id"]
    assert child
    assert child != parent
    stored = client.app.state.nets.get(net_id=child).summary
    assert (stored.parent_id, stored.reductions_applied, stored.places) == (
        parent,
        ("fuse-parallel-places",),
        2,
    )
    lineage = client.app.state.operations._runs.lineage_of(net_id=child)
    assert [(item.parent_id, item.rule) for item in lineage] == [(parent, "fuse-parallel-places")]
    # the reduced net is an ordinary net: it can be reduced again, and its history grows
    again, _ = reduce_through_the_api(client, child, "fuse-parallel-places")
    assert again.json()["data"]["changed"] is False
    assert again.json()["data"]["new_net_id"] is None
    assert client.app.state.nets.get(net_id=child).summary.places == 2


def test_asking_for_the_same_reduction_twice_gives_the_same_net(client):
    parent = client.post("/v1/nets", content=TWIN_PLACES, headers=XML).json()["net_id"]
    first, _ = reduce_through_the_api(client, parent, "fuse-parallel-places")
    second = ask(client, parent, "fuse-parallel-places")
    assert second.status_code == 200
    assert second.json()["data"]["new_net_id"] == first.json()["data"]["new_net_id"]


def test_protected_elements_are_part_of_the_question(client):
    parent = client.post("/v1/nets", content=TWIN_PLACES, headers=XML).json()["net_id"]
    both = {"parameters": {"protected": ["a", "b"]}}
    kept, _ = reduce_through_the_api(client, parent, "fuse-parallel-places", both)
    assert kept.json()["data"]["changed"] is False
    other, _ = reduce_through_the_api(client, parent, "fuse-parallel-places")
    assert other.json()["data"]["changed"] is True


def test_a_reduction_of_the_dead_part_leaves_the_rest_of_the_net_as_it_was(client):
    parent = client.post("/v1/nets", content=DEAD, headers=XML).json()["net_id"]
    answered, _ = reduce_through_the_api(client, parent, "remove-dead-transitions")
    child = client.app.state.nets.get(net_id=answered.json()["data"]["new_net_id"])
    assert child.summary.transitions == 1
    assert [t.name.text for t in child.document.pages[0].transitions] == ["live"]
    assert [p.name.text for p in child.document.pages[0].places] == ["never", "out", "p"]


def test_a_reduction_that_claims_a_change_but_gives_no_net_fails(settings):
    def drop_the_net(report):
        return report.model_copy(update={"reduced_pnml": None})

    app = create_app(
        settings=settings.model_copy(update={"operation_wait_seconds": 0}),
        engine_gateway=InProcessNative(tamper=drop_the_net),
    )
    client = TestClient(app)
    parent = client.post("/v1/nets", content=TWIN_PLACES, headers=XML).json()["net_id"]
    handle = ask(client, parent, "fuse-parallel-places").json()["data"]
    app.state.operations.drain()
    view = client.get(f"/v1/runs/{handle['run_id']}").json()["data"]
    assert (view["state"], view["error"]["code"]) == ("failed", "reduced_net_missing")


def test_a_reduction_that_claims_a_change_with_a_net_the_importer_refuses_fails(settings):
    def garbage(report):
        return report.model_copy(update={"reduced_pnml": b"<pnml><net/>"})

    app = create_app(
        settings=settings.model_copy(update={"operation_wait_seconds": 0}),
        engine_gateway=InProcessNative(tamper=garbage),
    )
    client = TestClient(app)
    parent = client.post("/v1/nets", content=TWIN_PLACES, headers=XML).json()["net_id"]
    handle = ask(client, parent, "fuse-parallel-places").json()["data"]
    app.state.operations.drain()
    view = client.get(f"/v1/runs/{handle['run_id']}").json()["data"]
    assert view["state"] == "failed"
    assert view["error"]["code"].startswith("runner_exception_")


def test_deleting_a_net_removes_the_lineage_of_its_children(client, settings):
    from app.infrastructure.sqlite_retention import SqliteRetention
    from tests.support import query

    parent = client.post("/v1/nets", content=TWIN_PLACES, headers=XML).json()["net_id"]
    answered, _ = reduce_through_the_api(client, parent, "fuse-parallel-places")
    assert query(path=settings.database_path, sql="SELECT count(*) FROM net_lineage") == [(1,)]
    SqliteRetention(path=settings.database_path).delete_net(
        net_id=answered.json()["data"]["new_net_id"]
    )
    assert query(path=settings.database_path, sql="SELECT count(*) FROM net_lineage") == [(0,)]
