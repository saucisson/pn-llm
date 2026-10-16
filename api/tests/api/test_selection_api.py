from fastapi.testclient import TestClient

from app.domain.models import EngineInfo
from app.main import create_app
from tests.support import MUTEX_PNML

XML = {"Content-Type": "application/pnml+xml"}
AST = {"op": "tokens", "place": "crit1", "cmp": ">=", "value": 1}


def test_capabilities_equivalence_and_filters_are_served(client):
    capabilities = client.get("/v1/engines/capabilities").json()["data"]
    assert {row["property_class"] for row in capabilities} >= {
        "state-cardinality",
        "ltl-fireability+next",
    }
    equivalence = client.get("/v1/engines/equivalence").json()["data"]
    assert all("engines" in row and "caveats" in row for row in equivalence)
    colored = client.get("/v1/engines", params={"colored": False}).json()["data"]
    assert "petrivet" in {e["name"] for e in colored}
    checking = client.get("/v1/engines", params={"can_check": "ltl-cardinality"}).json()["data"]
    assert {e["name"] for e in checking} == {"itstools", "tapaal", "ty"}
    assert checking[0]["examinations"]
    assert checking[0]["classes"]


class Listed:
    """An engine gateway that only lists engines: what the selection needs."""

    def __init__(self, *engines):
        self._engines = engines

    def list_engines(self):
        return self._engines


def engine(name, *, classes=("state-cardinality",), colored=False):
    return EngineInfo(
        name=name,
        version="1",
        logics=("state",),
        classes=classes,
        supports_colored=colored,
        available=True,
    )


def client_with(*engines, settings):
    return TestClient(create_app(settings=settings, engine_gateway=Listed(*engines)))


def test_selecting_tools_returns_the_engines_that_can_check_the_property(settings):
    client = client_with(
        engine("tapaal"), engine("itstools"), engine("blind", classes=()), settings=settings
    )
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    body = {"net_id": net_id, "formulas": [{"id": "f", "logic": "state", "ast": AST}]}
    envelope = client.post("/v1/select-tools", json=body).json()
    selection = envelope["data"]
    assert selection["property_classes"] == ["state-cardinality"]
    assert selection["basis"] == "preference"
    assert [r["engine"] for r in selection["ranked"]] == ["itstools", "tapaal"]
    assert selection["ranked"][0]["success_probability"] is None


def test_selecting_tools_with_no_capable_engine_is_a_clear_422_and_an_unknown_net_a_404(settings):
    client = client_with(engine("tapaal", classes=("ltl-cardinality",)), settings=settings)
    net_id = client.post("/v1/nets", content=MUTEX_PNML, headers=XML).json()["net_id"]
    body = {"net_id": net_id, "formulas": [{"id": "f", "logic": "state", "ast": AST}]}
    refused = client.post("/v1/select-tools", json=body)
    assert refused.status_code == 422
    assert "state-cardinality" in refused.json()["detail"]
    assert client.post("/v1/select-tools", json={**body, "net_id": "nope"}).status_code == 404
