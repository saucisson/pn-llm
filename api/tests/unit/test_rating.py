import json

import pytest

from app.domain.rating import Rating, agreements, build_sheet, kappa, rating_values
from tests.support import MUTEX_PNML
from tests.unit.test_experiment import ArcCounting, runner_over, spec


@pytest.fixture
def records(store):
    from app.domain.nets import NetFormat

    nets, runner = runner_over(store=store, engines=ArcCounting(trace_steps=("enter1",)))
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    base = runner.run_baseline(spec=spec(properties=6), net_id=net_id)
    other = base.model_copy(update={"spec": base.spec.model_copy(update={"condition": "L3"})})
    return base, other


def test_the_sheet_hides_the_condition_and_rates_an_identical_property_once(records):
    base, other = records
    sheet = build_sheet(records=(base, other), per_family=50, seed="s")
    shown = json.dumps([i.model_dump() for i in sheet.items])
    for leak in ("B0", "L3", "template", "b0-", "gloss"):
        assert leak not in shown
    assert len(sheet.items) == len(base.properties)  # both conditions wrote the same ones
    assert all({s.condition for s in k.sources} == {"B0", "L3"} for k in sheet.key)


def test_the_draw_is_seeded_bounded_and_shuffled(records):
    base, _ = records
    first = build_sheet(records=(base,), per_family=3, seed="a")
    assert first == build_sheet(records=(base,), per_family=3, seed="a")
    assert len(first.items) == 3
    other = build_sheet(records=(base,), per_family=6, seed="b")
    assert [i.item_id for i in other.items] != sorted(i.item_id for i in other.items)
    assert len({i.item_id for i in other.items}) == 6


def test_kappa_is_one_for_identical_raters_zero_for_chance_and_none_without_variation():
    same = (1, 0, 1, 1, 0, 0)
    assert kappa(a=same, b=same, categories=(0, 1), weighted=False) == 1.0
    assert kappa(a=(1, 1, 0, 0), b=(1, 0, 1, 0), categories=(0, 1), weighted=False) == 0.0
    assert kappa(a=(1, 1), b=(1, 1), categories=(0, 1), weighted=False) is None
    assert kappa(a=(), b=(), categories=(0, 1), weighted=False) is None
    near = kappa(a=(1, 2, 3, 4, 5), b=(2, 2, 3, 4, 4), categories=(1, 2, 3, 4, 5), weighted=True)
    far = kappa(a=(1, 2, 3, 4, 5), b=(5, 4, 3, 2, 1), categories=(1, 2, 3, 4, 5), weighted=True)
    assert near > 0.7
    assert far < 0


def rate(item, rater, score, keep):
    return Rating(item_id=item, rater=rater, score=score, keep=keep)


def test_agreement_is_reported_for_each_pair_on_shared_items_only():
    ratings = (
        rate("i1", "ann", 5, True),
        rate("i2", "ann", 1, False),
        rate("i3", "ann", 3, True),
        rate("i1", "bob", 5, True),
        rate("i2", "bob", 2, False),
        rate("i9", "bob", 4, True),
        rate("i1", "cat", 4, True),
    )
    by_pair = {(a.rater_a, a.rater_b): a for a in agreements(ratings=ratings)}
    assert set(by_pair) == {("ann", "bob"), ("ann", "cat"), ("bob", "cat")}
    assert by_pair[("ann", "bob")].items == 2
    assert by_pair[("ann", "cat")].keep_kappa is None  # one shared item: nothing to agree on


def test_ratings_become_per_condition_family_values_for_the_analysis(records):
    base, other = records
    sheet = build_sheet(records=(base, other), per_family=2, seed="s")
    first, second = (i.item_id for i in sheet.items)
    ratings = (
        rate(first, "ann", 5, True),
        rate(first, "bob", 3, True),
        rate(second, "ann", 1, False),
        rate(second, "bob", 1, False),
    )
    values = {
        (v.condition, v.measure): v.value for v in rating_values(sheet=sheet, ratings=ratings)
    }
    assert values[("B0", "M8_rating")] == pytest.approx(2.5)  # (4 + 1) / 2
    assert values[("L3", "M8_keep")] == pytest.approx(0.5)
    assert rating_values(sheet=sheet, ratings=()) == ()
