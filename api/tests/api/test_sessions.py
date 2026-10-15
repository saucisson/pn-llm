import json
import time

import pytest
from fastapi.testclient import TestClient

from app.domain.llm import LlmStep, LlmToolCall
from app.infrastructure.scripted_llm import ScriptedLlm
from app.main import create_app
from app.settings import Settings
from tests.support import MUTEX_PNML, ScriptedEngines

XML = {"Content-Type": "application/pnml+xml"}


def make_client(tmp_path, *, llm, **settings):
    config = Settings(database_path=tmp_path / "s.sqlite", embedded_workers=0, **settings)
    return TestClient(
        create_app(settings=config, engine_gateway=ScriptedEngines(), llm_gateway=llm)
    )


@pytest.fixture
def net_id_of():
    def register(client):
        return client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]

    return register


def ids(client, session_id):
    return [e["event"]["kind"] for e in events(client, session_id)]


def events(client, session_id, **params):
    return client.get(f"/v1/sessions/{session_id}/events", params=params).json()["data"]


def test_a_session_is_opened_runs_and_ends_its_turn(tmp_path, net_id_of):
    llm = ScriptedLlm(steps=(LlmStep(text="Hello."),))
    client = make_client(tmp_path, llm=llm)
    net_id = net_id_of(client)

    created = client.post("/v1/sessions", json={"net_id": net_id, "goal": "Is it safe?"})
    assert created.status_code == 201
    session = created.json()["data"]
    assert session["state"] == "queued"
    assert created.headers["location"] == f"/v1/sessions/{session['session_id']}"

    client.app.state.agent.run_next()
    assert client.get(f"/v1/sessions/{session['session_id']}").json()["data"]["state"] == "idle"
    assert ids(client, session["session_id"]) == [
        "session_started",
        "assistant_message",
        "run_finished",
    ]


def test_the_conversation_continues_with_messages(tmp_path, net_id_of):
    llm = ScriptedLlm(steps=(LlmStep(text="one"), LlmStep(text="two")))
    client = make_client(tmp_path, llm=llm)
    net_id = net_id_of(client)
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    client.app.state.agent.run_next()

    early = client.post(f"/v1/sessions/{sid}/messages", json={"text": "more"})
    assert early.status_code == 202
    assert early.json()["data"]["event"] == {"kind": "user_message", "text": "more"}
    client.app.state.agent.run_next()
    assert client.post(f"/v1/sessions/{sid}/messages", json={"text": "again"}).status_code == 202
    assert client.post(f"/v1/sessions/{sid}/messages", json={"text": "busy"}).status_code == 409


def test_a_question_is_answered_through_the_api(tmp_path, net_id_of):
    ask = LlmToolCall(
        call_id="ask-1", tool="ask_user", arguments=json.dumps({"question": "Which?"})
    )
    llm = ScriptedLlm(steps=(LlmStep(tool_calls=(ask,)), LlmStep(text="thanks")))
    client = make_client(tmp_path, llm=llm)
    net_id = net_id_of(client)
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    client.app.state.agent.run_next()

    assert client.get(f"/v1/sessions/{sid}").json()["data"]["state"] == "waiting_for_user"
    wrong = client.post(f"/v1/sessions/{sid}/answers", json={"question_id": "x", "text": "t"})
    assert wrong.status_code == 422
    ok = client.post(f"/v1/sessions/{sid}/answers", json={"question_id": "ask-1", "text": "this"})
    assert ok.status_code == 202
    client.app.state.agent.run_next()
    assert client.get(f"/v1/sessions/{sid}").json()["data"]["state"] == "idle"


def test_cancelling(tmp_path, net_id_of):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=()))
    net_id = net_id_of(client)
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    cancelled = client.post(f"/v1/sessions/{sid}/cancel")
    assert cancelled.json()["data"]["state"] == "cancelled"
    assert client.post(f"/v1/sessions/{sid}/messages", json={"text": "x"}).status_code == 409


def test_bad_requests(tmp_path, net_id_of):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=()))
    net_id = net_id_of(client)
    assert client.post("/v1/sessions", json={"net_id": "nope", "goal": "g"}).status_code == 404
    assert client.post("/v1/sessions", json={"net_id": net_id, "goal": ""}).status_code == 422
    assert (
        client.post("/v1/sessions", json={"net_id": net_id, "goal": "x" * 9000}).status_code == 422
    )
    other = {"net_id": net_id, "goal": "g", "description_id": "nope"}
    assert client.post("/v1/sessions", json=other).status_code == 404
    assert client.get("/v1/sessions/nope").status_code == 404
    assert client.get("/v1/sessions/nope/events").status_code == 404
    assert client.post("/v1/sessions/nope/cancel").status_code == 404


def test_events_can_be_read_after_a_number(tmp_path, net_id_of):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=(LlmStep(text="x"),)))
    net_id = net_id_of(client)
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    client.app.state.agent.run_next()
    tail = events(client, sid, after=1)
    assert [e["number"] for e in tail] == [2, 3]
    assert len(events(client, sid, limit=1)) == 1


def parse_sse(text):
    found = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "id" in fields:
            found.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return found


def test_events_stream_as_server_sent_events_and_resume_after_the_last_id(tmp_path, net_id_of):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=(LlmStep(text="x"),)))
    net_id = net_id_of(client)
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    client.app.state.agent.run_next()

    streamed = client.get(
        f"/v1/sessions/{sid}/events",
        params={"follow": "false"},
        headers={"Accept": "text/event-stream"},
    )
    assert streamed.headers["content-type"].startswith("text/event-stream")
    got = parse_sse(streamed.text)
    assert [(number, kind) for number, kind, _ in got] == [
        (1, "session_started"),
        (2, "assistant_message"),
        (3, "run_finished"),
    ]
    assert got[1][2]["event"]["text"] == "x"

    resumed = client.get(
        f"/v1/sessions/{sid}/events",
        params={"follow": "false"},
        headers={"Accept": "text/event-stream", "Last-Event-ID": "2"},
    )
    assert [number for number, _, _ in parse_sse(resumed.text)] == [3]


def test_the_offline_demonstration_runs_end_to_end_with_embedded_workers(tmp_path):
    config = Settings(
        database_path=tmp_path / "demo.sqlite",
        embedded_workers=2,
        worker_poll_seconds=0.02,
        llm_provider="scripted",
        tool_poll_seconds=0.01,
    )
    with TestClient(
        create_app(
            settings=config, engine_gateway=ScriptedEngines(verdict="UNKNOWN", trace_steps=())
        )
    ) as client:
        net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
        sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "Can it block?"}).json()[
            "data"
        ]["session_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            logged = [e["event"]["kind"] for e in events(client, sid)]
            if logged and logged[-1] == "run_finished":  # the state changes just before it
                break
            time.sleep(0.05)
        assert client.get(f"/v1/sessions/{sid}").json()["data"]["state"] == "idle"
        kinds = [e["event"]["kind"] for e in events(client, sid)]
        assert kinds.count("verdict") == 1
        verdict = next(e["event"] for e in events(client, sid) if e["event"]["kind"] == "verdict")
        assert verdict["verdict"] == "UNKNOWN"
        assert kinds[-1] == "run_finished"


def test_without_a_configured_model_a_session_explains_why(tmp_path):
    config = Settings(
        database_path=tmp_path / "none.sqlite", embedded_workers=1, worker_poll_seconds=0.02
    )
    with TestClient(create_app(settings=config)) as client:
        net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
        sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
            "session_id"
        ]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(events(client, sid)) < 3:
            time.sleep(0.05)
        error = events(client, sid)[1]["event"]
        assert error["code"] == "llm_unavailable"


def test_the_net_the_description_and_the_goal_can_come_in_one_multipart_request(tmp_path):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=(LlmStep(text="x"),)))
    created = client.post(
        "/v1/sessions/upload",
        files={
            "net": ("mutex.pnml", MUTEX_PNML, "application/xml"),
            "description_file": ("notes.md", b"# Two processes\nand a lock", "text/markdown"),
        },
        data={"goal": "Is it safe?"},
    )
    assert created.status_code == 201
    session = created.json()["data"]
    assert created.headers["location"] == f"/v1/sessions/{session['session_id']}"
    assert session["description_id"]
    started = events(client, session["session_id"])[0]["event"]
    assert (started["goal"], started["description_origin"]) == ("Is it safe?", "user")
    listed = client.get(f"/v1/nets/{session['net_id']}/descriptions").json()["data"]
    assert [d["text"] for d in listed] == ["# Two processes\nand a lock"]


def test_multipart_without_a_description_and_with_a_json_net(tmp_path):
    from app.domain.net_validation import DocumentLimits
    from app.domain.pnml_import import import_pnml

    document = import_pnml(payload=MUTEX_PNML, limits=DocumentLimits())
    client = make_client(tmp_path, llm=ScriptedLlm(steps=()))
    created = client.post(
        "/v1/sessions/upload",
        files={"net": ("mutex.json", document.model_dump_json().encode(), "application/json")},
        data={"goal": "g", "description": ""},
    )
    assert created.status_code == 201
    assert created.json()["data"]["description_id"] is None


def test_a_bad_net_in_a_multipart_request_is_a_422_and_creates_no_session(tmp_path):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=()))
    bad = client.post(
        "/v1/sessions/upload",
        files={"net": ("bad.pnml", b"<not xml", "application/xml")},
        data={"goal": "g"},
    )
    assert bad.status_code == 422
    assert bad.json()["location"] == "line 1"
    assert client.post("/v1/sessions/upload", data={"goal": "g"}).status_code == 422


def test_a_session_is_restarted_without_its_description_through_the_api(tmp_path, net_id_of):
    client = make_client(tmp_path, llm=ScriptedLlm(steps=()))
    net_id = net_id_of(client)
    client.post(
        f"/v1/nets/{net_id}/descriptions",
        content=b"about it",
        headers={"Content-Type": "text/plain"},
    )
    description_id = client.get(f"/v1/nets/{net_id}/descriptions").json()["data"][0][
        "description_id"
    ]
    sid = client.post(
        "/v1/sessions", json={"net_id": net_id, "goal": "g", "description_id": description_id}
    ).json()["data"]["session_id"]
    again = client.post(f"/v1/sessions/{sid}/restart", json={"with_description": False})
    assert again.status_code == 201
    assert again.json()["data"]["description_id"] is None
    assert again.json()["data"]["session_id"] != sid


def test_accepting_a_proposed_description_through_the_api(tmp_path, net_id_of):
    propose = LlmToolCall(
        call_id="p1", tool="propose_description", arguments=json.dumps({"text": "A lock."})
    )
    client = make_client(
        tmp_path, llm=ScriptedLlm(steps=(LlmStep(tool_calls=(propose,)), LlmStep(text="ok")))
    )
    net_id = net_id_of(client)
    sid = client.post("/v1/sessions", json={"net_id": net_id, "goal": "g"}).json()["data"][
        "session_id"
    ]
    client.app.state.agent.run_next()
    accepted = client.post(f"/v1/sessions/{sid}/description-proposals/p1/accept")
    assert accepted.status_code == 201
    assert accepted.json()["data"]["event"]["kind"] == "description_accepted"
    listed = client.get(f"/v1/nets/{net_id}/descriptions").json()["data"]
    assert [(d["text"], d["origin"]) for d in listed] == [("A lock.", "llm")]
    assert client.post(f"/v1/sessions/{sid}/description-proposals/p1/accept").status_code == 409
    assert client.post(f"/v1/sessions/{sid}/description-proposals/zzz/accept").status_code == 422
