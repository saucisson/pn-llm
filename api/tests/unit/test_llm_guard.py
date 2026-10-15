"""Guard: the net itself never reaches the LLM (ADR 0013, ADR 0015)."""

import json
from pathlib import Path

import pytest
from jsonschema import validate

from app.api.llm_tools import Operation, offered_to_llm
from app.domain.net_leak import contains_net
from tests.support import CHECK_BODY, MUTEX_DOCUMENT, MUTEX_PNML

SCHEMAS = Path(__file__).resolve().parents[3] / "docs" / "schemas"
XML = {"Content-Type": "application/pnml+xml"}

# Values for the parameters of the routes, to call every tool once.
PATH_VALUES = {"element_id": "enter1", "result_index": "0"}
QUERY_VALUES = {"ids": "enter1", "q": "e"}


def llm_operations(*, app):
    operations = []
    for path, item in app.openapi()["paths"].items():
        for method, operation in item.items():
            if offered_to_llm(operation=Operation(method=method, path=path)):
                operations.append((method, path, operation))
    return operations


def referenced_schemas(*, node, components, seen):
    """Collect the names of every component schema reachable from ``node``."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                name = value.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    referenced_schemas(node=components[name], components=components, seen=seen)
            else:
                referenced_schemas(node=value, components=components, seen=seen)
    elif isinstance(node, list):
        for item in node:
            referenced_schemas(node=item, components=components, seen=seen)
    return seen


def test_the_net_itself_routes_are_the_only_ones_excluded(client):
    all_routes = {
        (method, path) for path, item in client.app.openapi()["paths"].items() for method in item
    }
    offered = {(method, path) for method, path, _ in llm_operations(app=client.app)}
    assert all_routes - offered == {("post", "/v1/nets"), ("get", "/v1/nets/{net_id}")}
    assert offered  # there are tools


def test_no_tool_declares_a_net_in_its_responses(client):
    components = client.app.openapi()["components"]["schemas"]
    for method, path, operation in llm_operations(app=client.app):
        for status, response in operation["responses"].items():
            if not status.startswith("2"):
                continue
            content = response.get("content", {})
            assert set(content) <= {"application/json"}, (method, path, set(content))
            reachable = referenced_schemas(node=content, components=components, seen=set())
            assert "NetDocument" not in reachable, (method, path)


def test_no_tool_returns_a_net_when_called(scripted_client):
    client = scripted_client
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    job_id = client.post(f"/v1/nets/{net_id}/checks", json=CHECK_BODY).json()["data"]["job_id"]
    client.app.state.checks.drain()
    envelope = json.loads((SCHEMAS / "Envelope.schema.json").read_text())
    description = client.post(
        f"/v1/nets/{net_id}/descriptions",
        content=b"two processes",
        headers={"Content-Type": "text/plain"},
    ).json()["data"]["description_id"]
    session = client.post("/v1/sessions", json={"net_id": net_id, "goal": "is it safe?"}).json()
    values = {
        **PATH_VALUES,
        "job_id": job_id,
        "description_id": description,
        "session_id": session["data"]["session_id"],
    }
    called = 0
    for method, path, operation in llm_operations(app=client.app):
        if method != "get":
            continue
        url = path.replace("{net_id}", net_id)
        for name, value in values.items():
            url = url.replace("{" + name + "}", value)
        params = {
            parameter["name"]: QUERY_VALUES[parameter["name"]]
            for parameter in operation.get("parameters", [])
            if parameter["in"] == "query" and parameter.get("required")
        }
        response = client.get(url, params=params)
        assert response.status_code == 200, (url, response.text)
        assert not contains_net(text=response.text), url
        validate(instance=response.json(), schema=envelope)
        called += 1
    assert called >= 8


@pytest.mark.parametrize(
    "text",
    [
        MUTEX_PNML.decode(),
        '<?xml version="1.0"?><x/>',
        MUTEX_DOCUMENT.model_dump_json(exclude_none=True, exclude_defaults=True),
        json.dumps({"data": {"nested": [json.loads(MUTEX_DOCUMENT.model_dump_json())]}}),
    ],
    ids=["pnml", "xml-declaration", "document", "document-nested-in-an-envelope"],
)
def test_the_detector_catches_each_form_of_net(text):
    assert contains_net(text=text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain words",
        '{"id": "p1", "name": "idle", "kind": "place"}',
        '{"source_id": 3}',
        "[1, 2]",
    ],
)
def test_the_detector_lets_ordinary_results_through(text):
    assert not contains_net(text=text)
