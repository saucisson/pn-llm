from app.domain.mcc import MccNetFile, instance_of, parse_catalog
from tests.support import MUTEX_PNML
from tests.unit.test_mcc import PAGE


class OneNet:
    def catalog(self):
        return parse_catalog(page=PAGE)[:1]

    def nets(self, *, family):
        member = "Big/PT/big-1.pnml"
        yield MccNetFile(instance=instance_of(family=family, member=member), payload=MUTEX_PNML)


def test_seeded_models_are_listed_by_family_and_instance(client):
    client.app.state.models.seed(
        source=OneNet(), only_families=(), max_nets_per_family=None, with_properties=False
    )

    families = client.get("/v1/models/families").json()["data"]
    assert [(f["name"], f["net_type"]) for f in families] == [("Big", "pt")]

    listed = client.get("/v1/models", params={"family": "Big", "net_type": "pt"}).json()
    assert [(m["family"], m["instance"]) for m in listed["data"]] == [("Big", "big-1")]
    net_id = listed["data"][0]["net_id"]
    assert client.get(f"/v1/nets/{net_id}").status_code == 200
    assert client.get("/v1/models", params={"family": "Other"}).json()["data"] == []


def test_properties_of_a_net_are_served_per_examination(client):
    from tests.unit.test_model_catalog import FakeContestWithInputs

    client.app.state.models.seed(
        source=FakeContestWithInputs(),
        only_families=("Big",),
        max_nets_per_family=None,
        with_properties=True,
    )
    net_id = client.get("/v1/models", params={"family": "Big"}).json()["data"][0]["net_id"]
    served = client.get(f"/v1/models/{net_id}/properties/CTLCardinality").json()["data"]
    assert served["examination"] == "CTLCardinality"
    assert served["formulas"][0]["ast"] == {
        "op": "AG",
        "arg": {"op": "enabled", "transition": "t"},
    }
    assert client.get(f"/v1/models/{net_id}/properties/LTLCardinality").status_code == 404
    assert client.get(f"/v1/models/{net_id}/properties/Nope").status_code == 422


def test_published_results_are_summarized_per_tool_with_their_provenance(client):
    from app.domain.mcc_results import HEADER
    from tests.unit.test_mcc_results import ROWS
    from tests.unit.test_results_service import FakeContest

    client.app.state.results.import_results(
        source=FakeContest(lines=(f"### {HEADER}", *ROWS)), year=2026
    )
    summary = client.get("/v1/models/results/summary", params={"family": "Big"}).json()["data"]
    assert {row["tool"] for row in summary} == {"itstools", "petrivet", "ty"}
    sets = client.get("/v1/models/results/sets").json()["data"]
    assert (sets[0]["year"], sets[0]["runs"]) == (2026, 5)
    assert sets[0]["sha256"]


def test_a_frozen_split_is_served_by_name(client):
    from app.domain.mcc import parse_catalog
    from tests.unit.test_mcc import PAGE

    catalog = client.app.state.splits._catalog
    for family in parse_catalog(page=PAGE):
        catalog.save_family(family=family)
    client.app.state.splits.create(name="v1", seed="s", folds=2, test_fraction=0.0)
    assert client.get("/v1/models/splits").json()["data"] == ["v1"]
    served = client.get("/v1/models/splits/v1").json()["data"]
    assert {a["family"] for a in served["assignments"]} == {"Big", "Col", "Fs"}
    assert client.get("/v1/models/splits/nope").status_code == 404
