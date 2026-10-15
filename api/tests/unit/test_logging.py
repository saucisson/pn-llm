import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.application.checks import CheckService
from app.application.log_context import request_id
from app.infrastructure.json_logging import JsonFormatter, configure_logging
from app.main import create_app
from app.settings import Settings
from tests.support import LEASE, MUTEX_DOCUMENT, MUTEX_PNML, ScriptedEngines, make_request


def record(*, message="hello", **extra):
    made = logging.LogRecord("pnverif.test", logging.INFO, __file__, 1, message, (), None)
    made.__dict__.update(extra)
    return made


def test_a_record_is_one_json_object_with_its_extra_fields():
    line = JsonFormatter().format(record(job_id="j1", engine="itstools", duration_s=1.5))
    body = json.loads(line)
    assert (body["level"], body["logger"], body["message"]) == ("INFO", "pnverif.test", "hello")
    assert (body["job_id"], body["engine"], body["duration_s"]) == ("j1", "itstools", 1.5)
    assert body["time"].endswith("+00:00")
    assert "request_id" not in body
    assert "\n" not in line


def test_the_request_id_of_the_current_request_is_added():
    token = request_id.set("req-42")
    try:
        assert json.loads(JsonFormatter().format(record()))["request_id"] == "req-42"
    finally:
        request_id.reset(token)


def test_an_exception_is_logged_with_its_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        made = record()
        made.exc_info = sys.exc_info()
    assert "ValueError: boom" in json.loads(JsonFormatter().format(made))["exception"]


def test_configuring_twice_keeps_one_handler_of_ours_and_the_others(caplog):
    configure_logging(level="warning", as_json=True)
    configure_logging(level="info", as_json=False)
    ours = [h for h in logging.getLogger().handlers if h.get_name() == "pnverif"]
    assert len(ours) == 1
    assert not isinstance(ours[0].formatter, JsonFormatter)
    assert logging.getLogger().level == logging.INFO
    assert caplog.handler in logging.getLogger().handlers


def test_a_job_logs_its_life_without_any_net_content(store, caplog):
    from app.domain.canonical import net_id_of
    from app.domain.nets import summarize_document

    net = net_id_of(document=MUTEX_DOCUMENT)
    store.save_net(
        summary=summarize_document(document=MUTEX_DOCUMENT, net_id=net), document=MUTEX_DOCUMENT
    )
    checks = CheckService(
        nets=store, jobs=store, engines=ScriptedEngines(verdict="FALSE"), lease_seconds=LEASE
    )
    job_id = checks.submit(net_id=net, request=make_request()).job.job_id
    with caplog.at_level(logging.INFO, logger="pnverif.jobs"):
        checks.run_next()
    started, finished = [r for r in caplog.records if r.name == "pnverif.jobs"]
    assert (started.getMessage(), started.job_id, started.net_id) == ("job_started", job_id, net)
    assert finished.getMessage() == "job_finished"
    assert finished.verdicts == ["FALSE"]
    assert finished.duration_s >= 0
    assert finished.engine == "dummy"
    for logged in caplog.records:
        assert "<pnml" not in logged.getMessage()
        assert "idle1" not in json.dumps(logged.__dict__, default=str)


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(settings=Settings(database_path=tmp_path / "l.sqlite", embedded_workers=0))
    )


def test_every_response_carries_a_request_id_and_the_request_is_logged_with_it(client, caplog):
    with caplog.at_level(logging.INFO, logger="pnverif.http"):
        response = client.get("/v1/engines")
    sent = response.headers["x-request-id"]
    assert sent
    (logged,) = [r for r in caplog.records if r.name == "pnverif.http"]
    assert (logged.method, logged.path) == ("GET", "/v1/engines")
    assert logged.duration_ms >= 0


def test_a_sane_request_id_from_the_client_is_kept_and_a_hostile_one_replaced(client):
    kept = client.get("/v1/engines", headers={"X-Request-ID": "trace-123.a"})
    assert kept.headers["x-request-id"] == "trace-123.a"
    hostile = client.get("/v1/engines", headers={"X-Request-ID": 'x"}\n{"level":"FATAL'})
    assert hostile.headers["x-request-id"] != 'x"}\n{"level":"FATAL'
    assert len(hostile.headers["x-request-id"]) == 16


def test_uploading_a_net_logs_no_content(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(
            "/v1/nets", content=MUTEX_PNML, headers={"Content-Type": "application/pnml+xml"}
        )
    assert all("idle1" not in r.getMessage() for r in caplog.records)
