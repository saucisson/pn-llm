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
    client.app.state.models.seed(source=OneNet(), only_families=(), max_nets_per_family=None)

    families = client.get("/v1/models/families").json()["data"]
    assert [(f["name"], f["net_type"]) for f in families] == [("Big", "pt")]

    listed = client.get("/v1/models", params={"family": "Big", "net_type": "pt"}).json()
    assert [(m["family"], m["instance"]) for m in listed["data"]] == [("Big", "big-1")]
    net_id = listed["data"][0]["net_id"]
    assert client.get(f"/v1/nets/{net_id}").status_code == 200
    assert client.get("/v1/models", params={"family": "Other"}).json()["data"] == []
