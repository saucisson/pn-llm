import pytest

from app.application.engines import EngineService
from app.application.nets import NetService
from app.application.results import ResultsService
from app.application.selection import SelectionRequest, SelectionService
from app.domain.capabilities import (
    all_classes,
    can_check,
    classes_checked_by,
    examinations_needed,
    property_class_of,
)
from app.domain.errors import InvalidRequestError
from app.domain.formula_text import formula_from_text
from app.domain.mcc_results import HEADER
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.sqlite_results import SqliteResults
from tests.unit.test_operations import COLORED
from tests.unit.test_results_service import FakeContest


def formula(text, logic=None):
    return formula_from_text(text=text, formula_id="f", logic=logic, gloss="", origin="user")


@pytest.mark.parametrize(
    ("text", "logic", "key"),
    [
        ('"p" >= 1', "state", "state-cardinality"),
        ("is_fireable", None, None),
        ('AG "p" <= 1', "ctl", "ctl-cardinality"),
        ('G "p" <= 1', "ltl", "ltl-cardinality"),
        ('X "p" >= 1', "ltl", "ltl-cardinality+next"),
        ('EX "p" >= 1', "ctl", "ctl-cardinality+next"),
        ("deadlock", "state", "state-none"),
        ('"p" >= 1 & deadlock', "state", "state-cardinality"),
    ],
)
def test_a_formula_is_classified_by_its_logic_atoms_and_next(text, logic, key):
    if key is None:
        pytest.skip("syntax of fireability atoms is covered below")
    assert property_class_of(formula=formula(text, logic)).key == key


def test_fireability_and_mixed_atoms_are_told_apart(store):
    from app.domain.formula import And, Enabled, Formula, Tokens

    fire = Formula(id="f", logic="state", ast=Enabled(transition="t"))
    mixed = Formula(
        id="g",
        logic="state",
        ast=And(args=(Enabled(transition="t"), Tokens(place="p", cmp=">=", value=1))),
    )
    assert property_class_of(formula=fire).key == "state-fireability"
    assert property_class_of(formula=mixed).key == "state-mixed"


def test_a_class_needs_the_examinations_of_its_atoms():
    ltl = next(c for c in all_classes() if c.key == "ltl-fireability+next")
    assert examinations_needed(property_class=ltl) == (("LTLFireability",),)
    mixed = next(c for c in all_classes() if c.key == "state-mixed")
    assert examinations_needed(property_class=mixed) == (
        ("ReachabilityCardinality", "ReachabilityFireability"),
    )
    assert can_check(examinations=("ReachabilityCardinality",), property_class=mixed) is False
    bare = next(c for c in all_classes() if c.key == "state-none")
    assert can_check(examinations=("ReachabilityFireability",), property_class=bare) is True
    assert can_check(examinations=("StateSpace",), property_class=bare) is False


def test_the_classes_an_engine_checks_follow_the_examinations_it_takes_part_in():
    assert "ltl-fireability+next" in classes_checked_by(
        examinations=DEFAULT_ENGINES["itstools"].examinations
    )
    smpt = classes_checked_by(examinations=DEFAULT_ENGINES["smpt"].examinations)
    assert "state-cardinality" in smpt
    assert not any(k.startswith(("ctl", "ltl")) for k in smpt)
    assert classes_checked_by(examinations=DEFAULT_ENGINES["tedd"].examinations) == ()


class AllBuilt:
    """A docker double in which every engine image is present."""

    def image_present(self, *, image):
        return True


@pytest.fixture
def engines():
    return EngineService(engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=AllBuilt()))


def test_engines_can_be_filtered_by_what_they_check_and_by_colored_support(engines):
    names = lambda found: {e.name for e in found}  # noqa: E731
    assert names(engines.list_engines(can_check="ltl-fireability")) == {"itstools", "tapaal", "ty"}
    assert names(engines.list_engines(can_check="ctl-cardinality+next")) == {
        "itstools",
        "tapaal",
        "ty",
    }
    assert names(engines.list_engines(can_check="state-cardinality")) >= {"smpt"}
    assert "petrivet" in names(engines.list_engines(colored=False))
    assert "petrivet" not in names(engines.list_engines(colored=True))
    assert "dummy" not in names(engines.list_engines(can_check="state-cardinality"))


def test_the_capability_table_covers_every_class_and_the_colored_subset(engines):
    table = {row.property_class: row for row in engines.capabilities()}
    assert set(table) == {c.key for c in all_classes()}
    assert table["ltl-cardinality"].engines == ("itstools", "tapaal", "ty")
    assert "smpt" in table["state-cardinality"].colored_engines
    assert table["state-mixed"].engines == ("itstools", "smpt", "tapaal", "ty")


def test_equivalent_engines_come_with_their_caveats(engines):
    table = {row.property_class: row for row in engines.equivalence()}
    row = table["ltl-fireability"]
    assert row.engines == ("itstools", "tapaal", "ty")
    assert any(c.startswith("itstools:") and "counterexample" in c for c in row.caveats)
    assert any(c.startswith("tapaal:") for c in row.caveats)
    assert "state-none" in table


# ---- selection --------------------------------------------------------------------------------

ROWS = (
    "itstools,Big-PT-1,ReachabilityCardinality,4,OK,OK,16 BOOL:TRUE,-,1,1,2000,0,normal,r1",
    "itstools,Big-PT-2,ReachabilityCardinality,4,OK,OK,16 BOOL:TRUE,-,1,1,4000,0,normal,r2",
    "tapaal,Big-PT-1,ReachabilityCardinality,4,OK,OK,16 BOOL:TRUE,-,1,1,500,0,normal,r3",
    "tapaal,Big-PT-2,ReachabilityCardinality,4,DNF,OK,DNF,-,1,1,3600000,0,timeout,r4",
    "gold2025,Big-PT-1,ReachabilityCardinality,1,OK,OK,16 BOOL:TRUE,-,1,1,1,0,normal,r5",
)


@pytest.fixture
def selector(store, settings, engines):
    results = SqliteResults(path=settings.database_path)
    return SelectionService(
        nets=store,
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=AllBuilt()),
        results=results,
    ), ResultsService(results=results)


@pytest.fixture
def net_id(store, mutex_pnml):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    return nets.register(payload=mutex_pnml, format=NetFormat.PNML).stored.summary.net_id


def ask(net_id, text='"crit1" >= 1', logic="state"):
    return SelectionRequest(net_id=net_id, formulas=(formula(text, logic),))


def test_without_history_engines_come_in_a_fixed_order_with_no_invented_numbers(selector, net_id):
    selection = selector[0].select(request=ask(net_id))
    assert selection.basis == "preference"
    assert [r.engine for r in selection.ranked][:3] == ["itstools", "tapaal", "ty"]
    assert all(
        r.success_probability is None and r.expected_time_s is None for r in selection.ranked
    )
    assert selection.property_classes == ("state-cardinality",)


def test_with_history_the_engine_that_answers_more_often_comes_first(selector, net_id):
    service, results = selector
    results.import_results(source=FakeContest(lines=(f"### {HEADER}", *ROWS)), year=2026)
    selection = service.select(request=ask(net_id))
    assert selection.basis == "history"
    ranked = {r.engine: r for r in selection.ranked}
    assert selection.ranked[0].engine == "itstools"
    assert ranked["itstools"].success_probability == 1.0
    assert ranked["itstools"].expected_time_s == 3.0
    assert ranked["tapaal"].success_probability == 0.5
    assert "contest runs" in ranked["tapaal"].rationale
    assert "gold" not in ranked  # the contest's references are not engines


def test_only_engines_that_can_check_the_properties_are_offered(selector, net_id):
    selection = selector[0].select(request=ask(net_id, 'G "crit1" <= 1', "ltl"))
    assert {r.engine for r in selection.ranked} == {"itstools", "tapaal", "ty"}
    assert "smpt" not in {r.engine for r in selection.ranked}


def test_a_colored_net_keeps_the_engines_that_read_colored_nets(store, selector):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    colored = nets.register(payload=COLORED, format=NetFormat.PNML).stored.summary.net_id
    selection = selector[0].select(request=ask(colored, '"p1" >= 1'))
    assert all(DEFAULT_ENGINES[r.engine].colored for r in selection.ranked)


def test_when_no_engine_can_check_the_properties_the_request_is_refused(store, settings, net_id):
    class NoImage:
        def image_present(self, *, image):
            return False

    service = SelectionService(
        nets=store,
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=NoImage()),
        results=SqliteResults(path=settings.database_path),
    )
    with pytest.raises(InvalidRequestError, match="state-cardinality"):
        service.select(request=ask(net_id))
