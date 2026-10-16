import pytest
from pydantic import ValidationError

from app.domain.analyses.p_invariants import PInvariantsParameters, p_invariants
from app.domain.analyses.place_bounds import PlaceBoundsParameters, place_bounds
from app.domain.baseline import BaselineBudget, BaselineFacts, baseline_properties
from app.domain.formula_text import render_text
from app.domain.net_structure import build_structure
from tests.support import MUTEX_DOCUMENT


def mutex():
    return build_structure(document=MUTEX_DOCUMENT, net_id="n")


def facts(structure):
    return BaselineFacts(
        invariants=p_invariants(structure=structure, parameters=PInvariantsParameters()),
        bounds=place_bounds(structure=structure, parameters=PlaceBoundsParameters()),
    )


def generate(*, n=50, with_facts=True):
    structure = mutex()
    return baseline_properties(
        structure=structure,
        facts=facts(structure) if with_facts else BaselineFacts(),
        budget=BaselineBudget(max_properties=n),
    )


def test_the_standard_properties_of_each_family_are_written_with_their_ids():
    by_id = {f.id: f for f in generate()}
    assert render_text(expression=by_id["b0-deadlock-freedom"].ast) == "AG !deadlock"
    assert "AG EF" in render_text(expression=by_id["b0-home-state"].ast)
    assert render_text(expression=by_id["b0-quasi-live-enter1"].ast) == "EF fireable(enter1)"
    assert render_text(expression=by_id["b0-bounded-lock"].ast) == "AG (lock <= 1)"
    exclusions = [i for i in by_id if i.startswith("b0-exclusion-")]
    assert exclusions  # idle1, crit1 share an invariant worth one token
    assert {f.origin for f in by_id.values()} == {"template"}
    assert all(f.gloss for f in by_id.values())


def test_the_output_is_deterministic_and_cut_by_the_budget():
    assert generate() == generate()
    assert len(generate(n=3)) == 3
    assert generate(n=1)[0].id == "b0-deadlock-freedom"


def test_a_small_budget_still_touches_every_family():
    ids = [f.id for f in generate(n=5)]
    kinds = {i.split("-")[1] for i in ids}
    assert {"deadlock", "exclusion", "bounded", "quasi", "home"} <= kinds


def test_without_static_facts_there_are_no_exclusions_and_bounds_default_to_one_token():
    ids = [f.id for f in generate(with_facts=False)]
    assert not [i for i in ids if i.startswith("b0-exclusion-")]
    assert "b0-bounded-lock" in ids


def test_a_budget_of_zero_is_refused():
    with pytest.raises(ValidationError):
        BaselineBudget(max_properties=0)
