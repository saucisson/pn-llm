import pytest

from app.domain.analyses.dead_transitions import DeadTransitionsResult
from app.domain.analyses.invariants import WeightedElement
from app.domain.analyses.p_invariants import PInvariant, PInvariantsResult
from app.domain.analyses.place_bounds import PlaceBound, PlaceBoundsResult
from app.domain.contract import ElementRef, FiniteBound, UnboundedBound
from app.domain.formula_text import formula_from_text
from app.domain.triviality import StructuralFacts, triviality_of


def place(name):
    return ElementRef(id=name, name=name, kind="place")


FACTS = StructuralFacts(
    bounds=PlaceBoundsResult(
        bounds=(
            PlaceBound(place=place("crit"), bound=FiniteBound(value=1)),
            PlaceBound(place=place("lock"), bound=FiniteBound(value=1)),
            PlaceBound(place=place("queue"), bound=UnboundedBound()),
        ),
        total=3,
        finite=2,
        unbounded=1,
        unknown=0,
        largest_finite_bound=1,
        complete=True,
    ),
    invariants=PInvariantsResult(
        invariants=(
            PInvariant(
                elements=(
                    WeightedElement(element=place("crit"), weight=1),
                    WeightedElement(element=place("lock"), weight=1),
                ),
                constant=1,
            ),
        ),
        total=1,
        complete=True,
        uncovered_places=(place("queue"),),
    ),
    dead=DeadTransitionsResult(
        dead_transitions=(ElementRef(id="never", name="never", kind="transition"),),
        never_marked_places=(),
    ),
)


def kinds(text, logic=None):
    formula = formula_from_text(text=text, formula_id="f", logic=logic, gloss="", origin="llm")
    return [(t.kind, t.path) for t in triviality_of(formula=formula, facts=FACTS)]


@pytest.mark.parametrize(
    "text",
    [
        'AG "crit" <= 1',  # the bound already gives it
        'AG "crit" >= 0',  # tokens are never negative
        'AG ("crit" + "lock" <= 1)',  # a place invariant gives it
        'AG ("crit" <= 3 || "lock" >= 5)',
    ],
)
def test_a_property_the_structure_already_guarantees_is_reported_as_holding_in_every_state(text):
    assert kinds(text, "ctl") == [("holds_in_every_state", "")]


@pytest.mark.parametrize(
    "text",
    [
        'EF "crit" >= 2',  # more tokens than the place can hold
        "EF fireable(never)",
        'AG "lock" >= 2',
        'EF ("crit" >= 1 && "lock" >= 1) && "crit" >= 2',
    ],
)
def test_a_property_the_structure_rules_out_is_reported_as_holding_in_no_state(text):
    assert kinds(text, "ctl") == [("holds_in_no_state", "")]


def test_an_implication_with_an_impossible_premise_is_vacuous():
    found = kinds('AG ("crit" >= 2 -> "lock" >= 1)', "ctl")
    assert ("vacuous_antecedent", "/arg/left") in found
    assert ("holds_in_every_state", "") in found


def test_a_vacuous_premise_is_found_even_when_the_rest_is_not_trivial():
    found = kinds('"queue" >= 1 && ("crit" >= 2 -> "queue" >= 5)', "state")
    assert found == [("vacuous_antecedent", "/args/1/left")]


def test_properties_the_structure_does_not_decide_are_not_reported():
    for text, logic in [
        ('AG "crit" <= 0', "ctl"),
        ('EF "crit" >= 1', "ctl"),
        ('AG "queue" <= 5', "ctl"),
        ('AG ("crit" + "queue" <= 1)', "ctl"),
        ("deadlock", "state"),
        ('G (X "crit" <= 1)', "ltl"),
    ]:
        assert kinds(text, logic) == [], text


def test_without_facts_nothing_is_claimed():
    formula = formula_from_text(
        text='AG "crit" >= 0', formula_id="f", logic="ctl", gloss="", origin="llm"
    )
    findings = triviality_of(formula=formula, facts=StructuralFacts())
    assert [t.kind for t in findings] == ["holds_in_every_state"]  # tokens are never negative
    unbounded = formula_from_text(
        text='AG "crit" <= 1', formula_id="f", logic="ctl", gloss="", origin="llm"
    )
    assert triviality_of(formula=unbounded, facts=StructuralFacts()) == ()
