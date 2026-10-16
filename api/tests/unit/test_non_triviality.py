import pytest

from app.domain.non_triviality import (
    PropertyFindings,
    PropertySet,
    non_triviality_by_condition,
    score_property_set,
)
from app.domain.triviality import Triviality


def finding(kind):
    return Triviality(kind=kind, path="", explanation="x")


def subject(*, condition="B0", family="F", ids=("a", "b", "c", "d"), **findings):
    return PropertySet(
        condition=condition,
        family=family,
        property_ids=ids,
        findings=tuple(PropertyFindings(property_id=k, findings=v) for k, v in findings.items()),
    )


def test_vacuous_and_structure_decided_properties_are_trivial_and_a_double_one_counts_once():
    score = score_property_set(
        property_set=subject(
            a=(finding("vacuous_antecedent"),),
            b=(finding("holds_in_every_state"),),
            c=(finding("vacuous_antecedent"), finding("holds_in_no_state")),
        )
    )
    assert (score.properties, score.vacuous, score.decided_by_structure) == (4, 2, 2)
    assert score.non_trivial == 1
    assert score.share == 0.25


def test_a_family_without_properties_has_no_share_and_does_not_weigh_on_the_mean():
    empty = subject(family="E", ids=())
    full = subject(family="F", ids=("a", "b"), a=(finding("holds_in_every_state"),))
    (condition,) = non_triviality_by_condition(sets=(empty, full))
    assert [(f.family, f.share) for f in condition.families] == [("E", None), ("F", 0.5)]
    assert condition.mean_share == 0.5


def test_the_nets_of_a_family_are_pooled_and_families_weigh_the_same():
    big = subject(family="Big", ids=tuple("abcdefgh"))  # 8 non-trivial
    small = subject(family="Small", ids=("a", "b"), a=(finding("holds_in_every_state"),))
    again = subject(family="Small", ids=("a", "b"), b=(finding("vacuous_antecedent"),))
    (condition,) = non_triviality_by_condition(sets=(big, small, again))
    assert condition.mean_share == pytest.approx((1.0 + 0.5) / 2)  # not 10/12


def test_conditions_are_scored_apart_and_sorted():
    a = subject(condition="L3", ids=("a",), a=(finding("holds_in_every_state"),))
    b = subject(condition="B0", ids=("a",))
    scores = non_triviality_by_condition(sets=(a, b))
    assert [(s.condition, s.mean_share) for s in scores] == [("B0", 1.0), ("L3", 0.0)]
    assert non_triviality_by_condition(sets=()) == ()


def test_the_baseline_on_the_mutex_net_is_measured_with_the_products_own_filters():
    from app.domain.analyses.p_invariants import PInvariantsParameters, p_invariants
    from app.domain.analyses.place_bounds import PlaceBoundsParameters, place_bounds
    from app.domain.baseline import BaselineBudget, BaselineFacts, baseline_properties
    from app.domain.net_structure import build_structure
    from app.domain.triviality import StructuralFacts, triviality_of
    from tests.support import MUTEX_DOCUMENT

    structure = build_structure(document=MUTEX_DOCUMENT, net_id="n")
    invariants = p_invariants(structure=structure, parameters=PInvariantsParameters())
    bounds = place_bounds(structure=structure, parameters=PlaceBoundsParameters())
    formulas = baseline_properties(
        structure=structure,
        facts=BaselineFacts(invariants=invariants, bounds=bounds),
        budget=BaselineBudget(max_properties=50),
    )
    facts = StructuralFacts(bounds=bounds, invariants=invariants)
    measured = PropertySet(
        condition="B0",
        family="Mutex",
        property_ids=tuple(f.id for f in formulas),
        findings=tuple(
            PropertyFindings(property_id=f.id, findings=triviality_of(formula=f, facts=facts))
            for f in formulas
        ),
    )
    score = score_property_set(property_set=measured)
    # The bound and exclusion properties of B0 are implied by the invariants of the net: it is
    # the point of measuring them.
    assert score.decided_by_structure >= 3
    assert 0 < score.non_trivial < score.properties
