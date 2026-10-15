import pytest

from app.application.models import ModelCatalogService
from app.application.nets import NetService
from app.domain.contract import PageRequest
from app.domain.errors import NotFoundError
from app.domain.mcc import (
    MccInputNet,
    MccNetFile,
    MccNetType,
    PropertyFile,
    instance_of,
    parse_catalog,
)
from app.domain.net_validation import DocumentLimits
from app.infrastructure.sqlite_catalog import SqliteCatalog
from tests.support import MUTEX_PNML
from tests.unit.test_mcc import PAGE


class FakeContest:
    """A contest with one readable instance, one broken instance and one other family."""

    def catalog(self):
        return parse_catalog(page=PAGE)

    def nets(self, *, family):
        if family.name != "Big":
            return
        for member, payload in (
            ("Big/PT/big-1.pnml", MUTEX_PNML),
            ("Big/PT/big-2.pnml", b"<not xml"),
            ("Big/PT/big-3.pnml", MUTEX_PNML),
        ):
            yield MccNetFile(instance=instance_of(family=family, member=member), payload=payload)


CTL_XML = (
    b'<property-set xmlns="http://mcc.lip6.fr/"><property><id>p-00</id><description>d</description>'
    b"<formula><all-paths><globally><is-fireable><transition>t</transition></is-fireable>"
    b"</globally></all-paths></formula></property></property-set>"
)


class FakeContestWithInputs(FakeContest):
    def inputs(self, *, only_families):
        for instance in ("1", "2"):
            yield MccInputNet(
                family="Big",
                instance=instance,
                net_type=MccNetType.PT,
                name=f"Big-PT-{instance}",
                model=MUTEX_PNML,
                properties=(
                    PropertyFile(examination="CTLCardinality", xml=CTL_XML),
                    PropertyFile(examination="LTLCardinality", xml=b"<broken"),
                ),
            )
        yield MccInputNet(
            family="Col",
            instance="1",
            net_type=MccNetType.PT,
            name="Col-PT-1",
            model=MUTEX_PNML,
            properties=(),
        )


@pytest.fixture
def service(store, settings):
    return ModelCatalogService(
        catalog=SqliteCatalog(path=settings.database_path),
        nets=NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits()),
        descriptions=store,
    )


def seed(*, service, only=("Big",), cap=None):
    return service.seed(
        source=FakeContest(), only_families=only, max_nets_per_family=cap, with_properties=False
    )


def test_seeding_stores_nets_with_family_and_description_and_reports_failures(service, store):
    report = seed(service=service)
    assert (report.families, report.nets_stored, report.nets_already_known) == (1, 1, 1)
    assert [f.member for f in report.failures] == ["Big/PT/big-2.pnml"]
    entries = service.entries(family="Big", net_type=None, page=PageRequest(limit=10)).items
    assert [e.instance for e in entries] == ["big-1", "big-3"]
    assert entries[0].net_id == entries[1].net_id
    described = store.descriptions_of(net_id=entries[0].net_id)
    assert [(d.origin, d.text) for d in described] == [("mcc", "it models a big thing")]


def test_seeding_again_changes_nothing(service):
    seed(service=service)
    again = seed(service=service)
    assert again.nets_stored == 0
    assert len(service.entries(family=None, net_type=None, page=PageRequest(limit=10)).items) == 2


def test_the_cap_limits_the_nets_taken_per_family(service):
    report = seed(service=service, cap=1)
    assert report.nets_stored == 1
    assert report.failures == ()


def test_without_a_family_name_all_families_are_stored(service):
    report = seed(service=service, only=())
    assert report.families == 3
    assert [f.name for f in service.families()] == ["Big", "Col", "Fs"]


def test_entries_can_be_filtered_by_type(service):
    seed(service=service)
    assert (
        service.entries(family=None, net_type=MccNetType.COLORED, page=PageRequest(limit=5)).items
        == ()
    )


def test_seeding_with_properties_stores_the_formulas_and_reports_the_broken_file(service):
    report = service.seed(
        source=FakeContestWithInputs(),
        only_families=("Big",),
        max_nets_per_family=None,
        with_properties=True,
    )
    assert (report.nets_stored, report.nets_already_known) == (1, 1)
    assert report.property_sets_stored == 2
    assert [f.member for f in report.failures] == [
        "Big-PT-1/LTLCardinality.xml",
        "Big-PT-2/LTLCardinality.xml",
    ]
    net_id = service.entries(family="Big", net_type=None, page=PageRequest(limit=5)).items[0].net_id
    stored = service.properties(net_id=net_id, examination="CTLCardinality")
    assert stored.formulas[0].id == "p-00"
    assert stored.formulas[0].origin == "mcc"
    with pytest.raises(NotFoundError):
        service.properties(net_id=net_id, examination="LTLCardinality")


def test_the_cap_applies_to_inputs_too(service):
    report = service.seed(
        source=FakeContestWithInputs(),
        only_families=("Big",),
        max_nets_per_family=1,
        with_properties=True,
    )
    assert report.property_sets_stored == 1
