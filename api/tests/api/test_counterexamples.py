from tests.support import CHECK_BODY, MUTEX_PNML

XML = {"Content-Type": "application/pnml+xml"}

# A reachability goal: some reachable marking puts a token in the critical section.
GOAL = {
    "id": "reach",
    "logic": "state",
    "ast": {"op": "tokens", "place": "crit1", "cmp": ">=", "value": 1},
}


def register(client):
    return client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]


def check(client, net_id, **overrides):
    body = {**CHECK_BODY, "formulas": [GOAL], "engine": "scripted", **overrides}
    job_id = client.post(f"/v1/nets/{net_id}/checks", json=body).json()["data"]["job_id"]
    client.app.state.checks.drain()
    return job_id


def test_a_check_returns_the_envelope_and_the_result_cites_its_trace(scripted_client):
    net_id = register(scripted_client)
    job_id = check(scripted_client, net_id)
    body = scripted_client.get(f"/v1/jobs/{job_id}").json()
    assert body["tool"]["name"] == "check.get"
    result = body["data"]["results"][0]
    assert result["verdict"] == "FALSE"
    assert result["engine_version"] == "1.2.3"
    assert result["rendered"] == "native syntax"
    assert result["trace_url"] == f"/v1/jobs/{job_id}/results/0/trace"


def test_the_trace_is_served_in_the_envelope_on_the_original_net(scripted_client):
    net_id = register(scripted_client)
    job_id = check(scripted_client, net_id)
    body = scripted_client.get(f"/v1/jobs/{job_id}/results/0/trace").json()
    assert body["tool"]["name"] == "check.trace"
    trace = body["data"]
    assert trace["net_id"] == net_id
    assert trace["formula_id"] == "reach"
    assert trace["steps"] == [
        {"transition": {"id": "enter1", "name": "enter1", "kind": "transition"}}
    ]
    assert trace["loop_start"] is None
    assert {e["place"]["id"] for e in trace["initial_marking"]["entries"]} == {"idle1", "lock"}


def test_replaying_the_engines_counterexample_reaches_the_goal(scripted_client):
    """The engine claims a witness; the platform fires it and evaluates the goal itself."""
    net_id = register(scripted_client)
    job_id = check(scripted_client, net_id)
    trace = scripted_client.get(f"/v1/jobs/{job_id}/results/0/trace").json()["data"]
    steps = [step["transition"]["id"] for step in trace["steps"]]

    replay = scripted_client.post(
        f"/v1/nets/{net_id}/replay", json={"steps": steps, "state_formula": GOAL["ast"]}
    ).json()["data"]

    assert replay["valid"] is True
    assert replay["state_formula_holds"] is True


def test_replay_reports_where_a_trace_fails(scripted_client):
    net_id = register(scripted_client)
    body = {"steps": ["enter1", "enter1"]}
    response = scripted_client.post(f"/v1/nets/{net_id}/replay", json=body)
    data = response.json()["data"]
    assert data["valid"] is False
    assert data["failure"]["step"] == 1
    assert {m["place"]["id"] for m in data["failure"]["missing"]} == {"idle1", "lock"}


def test_replay_markings_are_paginated_through_the_envelope(scripted_client):
    net_id = register(scripted_client)
    steps = ["enter1", "leave1"] * 3
    first = scripted_client.post(
        f"/v1/nets/{net_id}/replay", json={"steps": steps, "page": {"limit": 3}}
    ).json()
    assert len(first["data"]["markings"]) == 3
    assert first["truncated"]["total"] == 7
    cursor = first["truncated"]["next_cursor"]
    second = scripted_client.post(
        f"/v1/nets/{net_id}/replay", json={"steps": steps, "page": {"limit": 3, "cursor": cursor}}
    ).json()
    assert second["data"]["markings_from"] == 3


def test_replay_with_a_bad_id_is_a_422_and_an_unknown_net_a_404(scripted_client):
    net_id = register(scripted_client)
    assert (
        scripted_client.post(f"/v1/nets/{net_id}/replay", json={"steps": ["zzz"]}).status_code
        == 422
    )
    assert scripted_client.post("/v1/nets/nope/replay", json={"steps": []}).status_code == 404


def test_trace_of_a_missing_result_or_without_a_trace_is_a_404(scripted_client):
    net_id = register(scripted_client)
    job_id = check(scripted_client, net_id)
    assert scripted_client.get(f"/v1/jobs/{job_id}/results/9/trace").status_code == 404
    assert scripted_client.get("/v1/jobs/nope/results/0/trace").status_code == 404


def test_cancelling_a_job_stops_its_engine(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.support import ScriptedEngines

    engines = ScriptedEngines()
    client = TestClient(create_app(settings=settings, engine_gateway=engines))
    net_id = register(client)
    job_id = check(client, net_id)
    assert client.delete(f"/v1/jobs/{job_id}").status_code == 204
    assert engines.stopped == [job_id]


def test_an_engine_that_cites_an_unknown_transition_gets_no_verdict(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.support import ScriptedEngines

    client = TestClient(
        create_app(settings=settings, engine_gateway=ScriptedEngines(trace_steps=("ghost",)))
    )
    net_id = register(client)
    job_id = check(client, net_id)
    result = client.get(f"/v1/jobs/{job_id}").json()["data"]["results"][0]
    assert result["verdict"] == "ERROR"
    assert "ghost" in result["warnings"][0]
    assert result["trace_url"] is None
