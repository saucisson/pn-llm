from tests.support import CHECK_BODY, MUTEX_PNML, make_formula

XML = {"Content-Type": "application/pnml+xml"}


def register(client):
    return client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]


def validate(client, **body):
    return client.post("/v1/formulas/validate", json=body)


def test_validating_text_returns_the_tree_and_canonical_text(client):
    net_id = register(client)
    response = validate(client, net_id=net_id, text="G !(crit1 >= 1 && lock >= 2)", id="mutex")
    assert response.status_code == 200
    body = response.json()
    assert body["tool"]["name"] == "formula.validate"
    data = body["data"]
    assert data["valid"] is True
    assert data["formula"]["logic"] == "ltl"
    assert data["formula"]["id"] == "mutex"
    assert data["formula"]["ast"]["op"] == "G"
    assert data["text"] == "G !(crit1 >= 1 && lock >= 2)"


def test_validating_a_tree(client):
    net_id = register(client)
    response = validate(client, net_id=net_id, formula=CHECK_BODY["formulas"][0])
    assert response.json()["data"]["valid"] is True


def test_errors_are_reported_not_raised(client):
    net_id = register(client)
    unknown = validate(client, net_id=net_id, text="G nope >= 1").json()["data"]
    assert unknown["valid"] is False
    assert unknown["errors"][0]["code"] == "unknown_place"
    syntax = validate(client, net_id=net_id, text="G (").json()["data"]
    assert syntax["valid"] is False
    assert syntax["formula"] is None
    assert syntax["errors"][0]["code"] == "syntax_error"
    assert "offset 3" in syntax["errors"][0]["message"]


def test_a_request_with_neither_tree_nor_text_is_a_422(client):
    assert validate(client, net_id=register(client)).status_code == 422


def test_unknown_net_is_a_404(client):
    assert validate(client, net_id="nope", text="deadlock").status_code == 404


def test_a_check_with_an_unknown_id_is_a_422_pointing_at_the_formula(client):
    net_id = register(client)
    bad = {
        **make_formula(formula_id="f"),
        "ast": {"op": "tokens", "place": "crit", "cmp": ">=", "value": 1},
    }
    response = client.post(f"/v1/nets/{net_id}/checks", json={**CHECK_BODY, "formulas": [bad]})
    assert response.status_code == 422
    problem = response.json()
    assert problem["location"] == "/formulas/0/ast/place"
    assert "crit1" in problem["detail"]


def test_a_check_with_an_operator_of_the_wrong_logic_is_a_422(client):
    net_id = register(client)
    bad = {
        **make_formula(formula_id="f"),
        "logic": "ltl",
        "ast": {"op": "EF", "arg": make_formula(formula_id="x")["ast"]},
    }
    response = client.post(f"/v1/nets/{net_id}/checks", json={**CHECK_BODY, "formulas": [bad]})
    assert response.status_code == 422
    assert response.json()["location"] == "/formulas/0/ast"
