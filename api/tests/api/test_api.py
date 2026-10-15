import time

from fastapi.testclient import TestClient

from app.domain.models import Job, JobState
from app.main import create_app
from app.settings import Settings
from tests.support import CHECK_BODY, MUTEX_PNML, make_request

XML = {"Content-Type": "application/pnml+xml"}


def upload(client):
    response = client.post("/v1/nets", content=MUTEX_PNML, headers=XML)
    assert response.status_code in {200, 201}
    body = response.json()
    return {"net_id": body["net_id"], "created": body["created"], "summary": body["summary"]}


def start(client, net_id, body=CHECK_BODY):
    """Queue a check and let the workers run it: the test client starts none of its own."""
    response = client.post(f"/v1/nets/{net_id}/checks", json=body)
    client.app.state.checks.drain()
    return response


# ---- nets -----------------------------------------------------------------------------------


def test_upload_summarizes_the_net_and_keeps_names(client):
    net = upload(client)
    summary = net["summary"]
    assert (summary["places"], summary["transitions"], summary["arcs"]) == (3, 2, 6)
    assert net["summary"]["kind"] == "pt"
    assert net["summary"]["initial_tokens"] == 2
    assert "place_names" not in net["summary"]


def test_upload_is_idempotent(client):
    assert upload(client)["net_id"] == upload(client)["net_id"]


def test_get_net_returns_the_document(client):
    net_id = upload(client)["net_id"]
    document = client.get(f"/v1/nets/{net_id}").json()
    assert document["source_id"] == "mutex"
    assert [place["id"] for place in document["pages"][0]["places"]] == ["crit1", "idle1", "lock"]


def test_invalid_pnml_is_a_422_problem(client):
    response = client.post("/v1/nets", content=b"<not xml", headers=XML)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "Invalid XML" in response.json()["detail"]
    assert response.json()["location"] == "line 1"


def test_empty_net_is_rejected(client):
    assert (
        client.post(
            "/v1/nets",
            content=b"<pnml><net id='n' type='t'><page id='p'/></net></pnml>",
            headers=XML,
        ).status_code
        == 422
    )


def test_oversized_upload_is_a_413(tmp_path):
    settings = Settings(database_path=tmp_path / "small.sqlite", max_upload_bytes=10)
    small = TestClient(create_app(settings=settings))
    assert small.post("/v1/nets", content=MUTEX_PNML, headers=XML).status_code == 413


def test_unknown_net_is_a_404_problem(client):
    response = client.get("/v1/nets/doesnotexist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


# ---- checks and jobs ------------------------------------------------------------------------


def test_check_lifecycle_with_the_dummy_engine(client):
    net_id = upload(client)["net_id"]
    response = start(client, net_id)
    assert response.status_code == 202
    job = client.get(f"/v1/jobs/{response.json()['data']['job_id']}").json()["data"]
    assert job["state"] == "done"  # TestClient runs background tasks before returning
    # The dummy engine verifies nothing: it must NEVER answer TRUE or FALSE
    assert job["results"][0]["verdict"] == "UNKNOWN"


def test_same_request_returns_the_same_job(client):
    net_id = upload(client)["net_id"]
    assert (
        start(client, net_id).json()["data"]["job_id"]
        == start(client, net_id).json()["data"]["job_id"]
    )


def test_different_limits_make_a_different_job(client):
    net_id = upload(client)["net_id"]
    other = {**CHECK_BODY, "limits": {"timeout_s": 10, "memory_mb": 512}}
    assert (
        start(client, net_id).json()["data"]["job_id"]
        != start(client, net_id, other).json()["data"]["job_id"]
    )


def test_unknown_engine_is_a_422(client):
    net_id = upload(client)["net_id"]
    body = {**CHECK_BODY, "engine": "nope"}
    assert start(client, net_id, body).status_code == 422


def test_invalid_body_is_rejected(client):
    net_id = upload(client)["net_id"]
    assert start(client, net_id, {"formulas": []}).status_code == 422


def test_check_on_unknown_net_is_a_404(client):
    assert start(client, "nope").status_code == 404


def test_unknown_job_is_a_404(client):
    assert client.get("/v1/jobs/nope").status_code == 404
    assert client.delete("/v1/jobs/nope").status_code == 404


def test_cancelling_a_finished_job_keeps_its_results(client):
    net_id = upload(client)["net_id"]
    job_id = start(client, net_id).json()["data"]["job_id"]
    assert client.delete(f"/v1/jobs/{job_id}").status_code == 204
    job = client.get(f"/v1/jobs/{job_id}").json()["data"]
    assert job["state"] == "done"
    assert job["results"]


# ---- engines --------------------------------------------------------------------------------


def test_engines_are_listed_with_capabilities(client):
    engines = {e["name"]: e for e in client.get("/v1/engines").json()["data"]}
    assert engines["dummy"]["available"] is True
    assert engines["petrivet"]["supports_colored"] is False
    assert engines["itstools"]["supports_colored"] is True


# ---- persistence and settings ---------------------------------------------------------------


def test_nets_and_jobs_survive_a_restart(settings):
    first = TestClient(create_app(settings=settings))
    net_id = upload(first)["net_id"]
    job_id = start(first, net_id).json()["data"]["job_id"]

    second = TestClient(create_app(settings=settings))  # new process, same database file
    assert len(second.get(f"/v1/nets/{net_id}").json()["pages"][0]["places"]) == 3
    job = second.get(f"/v1/jobs/{job_id}").json()["data"]
    assert job["state"] == "done"
    assert job["results"][0]["engine"] == "dummy"
    assert start(second, net_id).json()["data"]["job_id"] == job_id  # idempotent across restarts


def test_the_sweeper_interrupts_orphans_but_not_live_or_queued_jobs(tmp_path):
    settings = Settings(database_path=tmp_path / "sweep.sqlite", embedded_workers=0)
    app = create_app(settings=settings)
    net_id = upload(TestClient(app))["net_id"]
    jobs = app.state.checks._jobs
    for name, engine in (("orphan", "dummy"), ("alive", "itstools"), ("waiting", "tapaal")):
        jobs.create_or_get_job(
            job=Job(
                job_id=name,
                net_id=net_id,
                state=JobState.QUEUED,
                request=make_request(engine=engine),
            )
        )
    jobs.claim_next_job(lease_seconds=-1)  # orphan: claimed, then its owner died
    jobs.claim_next_job(lease_seconds=60)

    with TestClient(create_app(settings=settings)) as other_process:  # runs the lifespan sweeper
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if other_process.get("/v1/jobs/orphan").json()["data"]["state"] == "interrupted":
                break
            time.sleep(0.05)
        assert other_process.get("/v1/jobs/orphan").json()["data"]["state"] == "interrupted"
        assert other_process.get("/v1/jobs/alive").json()["data"]["state"] == "running"
        assert other_process.get("/v1/jobs/waiting").json()["data"]["state"] == "queued"


def test_a_lost_job_can_be_retried_through_the_api(tmp_path):
    settings = Settings(database_path=tmp_path / "retry.sqlite", embedded_workers=0)
    app = create_app(settings=settings)
    client = TestClient(app)
    net_id = upload(client)["net_id"]
    job_id = client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY).json()["data"]["job_id"]
    app.state.checks._jobs.claim_next_job(lease_seconds=-1)
    app.state.checks.recover_interrupted()

    assert client.get(f"/v1/jobs/{job_id}").json()["data"]["state"] == "interrupted"
    retried = client.post(f"/v1/jobs/{job_id}/retry")
    assert retried.status_code == 202
    assert retried.json()["data"]["state"] == "queued"
    app.state.checks.drain()
    assert client.get(f"/v1/jobs/{job_id}").json()["data"]["state"] == "done"


def test_retrying_a_job_that_was_not_interrupted_is_a_422_and_an_unknown_one_a_404(client):
    net_id = upload(client)["net_id"]
    job_id = start(client, net_id).json()["data"]["job_id"]
    assert client.post(f"/v1/jobs/{job_id}/retry").status_code == 422
    assert client.post("/v1/jobs/nope/retry").status_code == 404


def test_retrying_while_an_equivalent_job_is_live_is_a_409(tmp_path):
    settings = Settings(database_path=tmp_path / "conflict.sqlite", embedded_workers=0)
    app = create_app(settings=settings)
    client = TestClient(app)
    net_id = upload(client)["net_id"]
    old = client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY).json()["data"]["job_id"]
    app.state.checks._jobs.claim_next_job(lease_seconds=-1)
    app.state.checks.recover_interrupted()
    client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY)  # a new live job takes the key
    assert client.post(f"/v1/jobs/{old}/retry").status_code == 409


def test_embedded_workers_run_queued_jobs_without_any_help(tmp_path):
    settings = Settings(
        database_path=tmp_path / "workers.sqlite", embedded_workers=2, worker_poll_seconds=0.02
    )
    with TestClient(create_app(settings=settings)) as client:
        net_id = upload(client)["net_id"]
        job_id = client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY).json()["data"]["job_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if client.get(f"/v1/jobs/{job_id}").json()["data"]["state"] == "done":
                break
            time.sleep(0.05)
        assert client.get(f"/v1/jobs/{job_id}").json()["data"]["state"] == "done"


def test_settings_come_from_the_environment(tmp_path, monkeypatch):
    target = tmp_path / "from_env.sqlite"
    monkeypatch.setenv("PNVERIF_DATABASE_PATH", str(target))
    create_app()
    assert target.exists()


def test_the_sweeper_purges_old_finished_jobs_when_retention_is_set(tmp_path):
    import sqlite3

    settings = Settings(
        database_path=tmp_path / "retention.sqlite", job_lease_seconds=0.2, job_retention_days=1
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    net_id = upload(client)["net_id"]
    job_id = start(client, net_id).json()["data"]["job_id"]
    conn = sqlite3.connect(settings.database_path)
    conn.execute("UPDATE jobs SET updated_at=0")
    conn.commit()
    conn.close()

    with TestClient(app) as running:  # runs the lifespan sweeper
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if running.get(f"/v1/jobs/{job_id}").status_code == 404:
                break
            time.sleep(0.05)
        assert running.get(f"/v1/jobs/{job_id}").status_code == 404
        assert running.get(f"/v1/nets/{net_id}").status_code == 200


def test_the_built_ui_is_served_under_ui_when_a_directory_is_given(tmp_path):
    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<html>chat</html>")
    settings = Settings(database_path=tmp_path / "ui.sqlite", ui_dir=built)
    client = TestClient(create_app(settings=settings))
    assert client.get("/ui/").text == "<html>chat</html>"
    assert client.get("/v1/engines").status_code == 200


def test_there_is_no_ui_route_without_a_directory(client):
    assert client.get("/ui/").status_code == 404
