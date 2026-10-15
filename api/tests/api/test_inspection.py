import json

import pytest

from tests.support import MUTEX_PNML, make_ring

XML = {"Content-Type": "application/pnml+xml"}


def register(client, *, payload=MUTEX_PNML):
    return client.post("/v1/nets", content=payload, headers=XML).json()["net_id"]


@pytest.fixture
def net_id(client):
    return register(client)


def get(client, net_id, path, **params):
    return client.get(f"/v1/nets/{net_id}/{path}", params=params)


def test_summary_has_counts_and_flags_but_no_names(client, net_id):
    body = get(client, net_id, "summary").json()
    assert body["schema_version"] == "1.0"
    assert body["tool"]["name"] == "net.summary"
    assert body["net_id"] == net_id
    data = body["data"]
    assert data["size_category"] == "small"
    assert data["has_weighted_arcs"] is False
    assert data["summary"]["places"] == 3
    assert "idle1" not in json.dumps(body)


def test_places_are_sorted_by_id_and_keep_names(client, net_id):
    data = get(client, net_id, "places").json()["data"]
    assert [p["id"] for p in data] == ["crit1", "idle1", "lock"]
    assert data[1] == {"id": "idle1", "name": "idle1", "kind": "place"}


def test_places_filter_by_name_and_marking(client, net_id):
    assert [p["id"] for p in get(client, net_id, "places", name="*1").json()["data"]] == [
        "crit1",
        "idle1",
    ]
    assert [p["id"] for p in get(client, net_id, "places", marked="true").json()["data"]] == [
        "idle1",
        "lock",
    ]
    assert [p["id"] for p in get(client, net_id, "places", marked="false").json()["data"]] == [
        "crit1"
    ]


def test_transitions_and_arcs(client, net_id):
    transitions = get(client, net_id, "transitions").json()["data"]
    assert [t["id"] for t in transitions] == ["enter1", "leave1"]
    arcs = get(client, net_id, "arcs", source="enter1").json()["data"]
    assert [(a["id"], a["target"]["id"], a["weight"]) for a in arcs] == [("a3", "crit1", 1)]
    into = get(client, net_id, "arcs", target="enter1").json()["data"]
    assert {a["source"]["id"] for a in into} == {"idle1", "lock"}


def test_pagination_is_explicit_and_resumable(client):
    net_id = register(client, payload=make_ring(size=10))
    first = get(client, net_id, "places", limit=7).json()
    assert len(first["data"]) == 7
    assert first["truncated"]["total"] == 30
    assert first["truncated"]["returned"] == 7
    cursor = first["truncated"]["next_cursor"]
    seen = [p["id"] for p in first["data"]]
    while cursor:
        page = get(client, net_id, "places", limit=7, cursor=cursor).json()
        seen += [p["id"] for p in page["data"]]
        cursor = page["truncated"]["next_cursor"] if page["truncated"] else None
    assert seen == sorted(seen)
    assert len(seen) == 30
    complete = get(client, net_id, "places", limit=500).json()
    assert complete["truncated"] is None


def test_a_bad_cursor_is_a_422_problem(client, net_id):
    response = get(client, net_id, "places", cursor="garbage")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_page_limit_is_bounded(client, net_id):
    assert get(client, net_id, "places", limit=501).status_code == 422
    assert get(client, net_id, "places", limit=0).status_code == 422


def test_element_detail_lists_weighted_neighbours(client, net_id):
    data = get(client, net_id, "elements/enter1").json()["data"]
    assert data["element"] == {"id": "enter1", "name": "enter1", "kind": "transition"}
    assert {n["element"]["id"] for n in data["inputs"]["items"]} == {"idle1", "lock"}
    assert data["outputs"]["total"] == 1
    place = get(client, net_id, "elements/idle1").json()["data"]
    assert place["tokens"] == 1
    assert place["inputs"]["items"][0]["element"]["id"] == "leave1"


def test_unknown_element_is_a_404_with_suggestions(client, net_id):
    response = get(client, net_id, "elements/enter")
    assert response.status_code == 404
    assert "enter1" in response.json()["detail"]


def test_search_finds_names_and_ids_ignoring_case(client, net_id):
    found = get(client, net_id, "search", q="ENTER").json()["data"]
    assert [e["id"] for e in found] == ["enter1"]
    wildcard = get(client, net_id, "search", q="*1").json()["data"]
    assert len(wildcard) == 4
    assert get(client, net_id, "search", q="").status_code == 422


def test_marking_is_sparse_and_sorted(client, net_id):
    data = get(client, net_id, "marking").json()["data"]
    assert [(e["place"]["id"], e["tokens"]) for e in data["entries"]] == [("idle1", 1), ("lock", 1)]


def test_neighbourhood_has_distances_and_internal_arcs(client, net_id):
    data = get(client, net_id, "neighbourhood", ids="enter1", depth=1).json()["data"]
    distances = {e["element"]["id"]: e["distance"] for e in data["elements"]}
    assert distances == {"enter1": 0, "idle1": 1, "lock": 1, "crit1": 1}
    assert {a["id"] for a in data["arcs"]} == {"a1", "a2", "a3"}
    assert data["cut"] is False


def test_neighbourhood_is_capped_with_a_cut_marker(client, net_id):
    data = get(client, net_id, "neighbourhood", ids="enter1", depth=3, max_elements=3).json()[
        "data"
    ]
    assert len(data["elements"]) == 3
    assert data["cut"] is True


def test_neighbourhood_validates_its_input(client, net_id):
    assert get(client, net_id, "neighbourhood", ids="nope").status_code == 404
    assert get(client, net_id, "neighbourhood", ids="enter1", depth=9).status_code == 422
    assert get(client, net_id, "neighbourhood", ids="enter1", max_elements=0).status_code == 422
    assert get(client, net_id, "neighbourhood").status_code == 422


def test_name_groups_compress_indexed_names(client):
    net_id = register(client, payload=make_ring(size=12))
    data = get(client, net_id, "name-groups").json()["data"]
    by_pattern = {g["pattern"]: g for g in data}
    assert set(by_pattern) == {"fork_{}", "think_{}", "eat_{}", "take_{}"}
    fork = by_pattern["fork_{}"]
    assert fork["count"] == 12
    assert fork["indices"] == [{"min": 1, "max": 12, "distinct": 12, "width": None}]
    assert fork["kind"] == "place"
    assert fork["example"]["id"] == "fork1"


def test_unknown_net_is_404_on_every_route(client):
    for path in ("summary", "places", "transitions", "arcs", "marking", "name-groups"):
        assert get(client, "nope", path).status_code == 404
