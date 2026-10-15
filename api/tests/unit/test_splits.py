import pytest

from app.application.splits import SplitService
from app.domain.errors import ConflictError, InvalidRequestError, NotFoundError
from app.domain.mcc import parse_catalog
from app.domain.splits import make_split
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_splits import SqliteSplits
from tests.unit.test_mcc import PAGE

NAMES = tuple(f"Family{index:02d}" for index in range(23))


def split(*, seed="s", folds=4, fraction=0.2, families=NAMES):
    return make_split(name="x", seed=seed, folds=folds, test_fraction=fraction, families=families)


def test_every_family_goes_to_exactly_one_place_and_folds_are_balanced():
    result = split()
    assert sorted(a.family for a in result.assignments) == sorted(NAMES)
    tests = [a for a in result.assignments if a.role == "test"]
    assert len(tests) == 5  # ceil(0.2 * 23)
    assert all(a.fold is None for a in tests)
    sizes = [sum(a.fold == fold for a in result.assignments) for fold in range(4)]
    assert max(sizes) - min(sizes) <= 1
    assert sum(sizes) == 18


def test_the_same_inputs_give_the_same_split_in_any_order_and_the_seed_changes_it():
    assert split() == split(families=tuple(reversed(NAMES)))
    assert split(seed="other") != split()


def test_too_few_families_for_the_folds_are_refused():
    with pytest.raises(InvalidRequestError):
        split(families=NAMES[:4], folds=5)


def test_a_service_freezes_a_split_of_the_catalog_and_refuses_to_replace_it(settings):
    catalog = SqliteCatalog(path=settings.database_path)
    for family in parse_catalog(page=PAGE):
        catalog.save_family(family=family)
    service = SplitService(splits=SqliteSplits(path=settings.database_path), catalog=catalog)
    created = service.create(name="v1", seed="s", folds=2, test_fraction=0.0)
    assert service.get(name="v1") == created
    assert service.names() == ("v1",)
    assert [a.family for a in created.assignments] == ["Big", "Col", "Fs"]
    with pytest.raises(ConflictError):
        service.create(name="v1", seed="other", folds=2, test_fraction=0.0)
    assert service.get(name="v1") == created
    with pytest.raises(NotFoundError):
        service.get(name="nope")
