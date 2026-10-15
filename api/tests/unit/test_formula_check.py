import pytest
from pydantic import ValidationError

from app.domain.formula import Formula
from app.domain.formula_check import FormulaValidationRequest, check_formula
from app.domain.formula_text import formula_from_text
from app.domain.net_structure import build_structure
from tests.support import MUTEX_DOCUMENT, make_request

STRUCTURE = build_structure(document=MUTEX_DOCUMENT, net_id="n")


def check(text, *, logic=None):
    formula = formula_from_text(text=text, formula_id="f", logic=logic, gloss="", origin="user")
    return check_formula(formula=formula, structure=STRUCTURE)


def test_a_good_formula_is_valid_and_comes_back_as_canonical_text():
    report = check("G !(crit1 >= 1 && lock >= 2)")
    assert report.valid
    assert report.errors == ()
    assert report.warnings == ()
    assert report.atoms.cardinality is True
    assert report.atoms.fireability is False
    assert report.text == "G !(crit1 >= 1 && lock >= 2)"


def test_unknown_ids_are_rejected_with_the_closest_matches_and_a_path():
    report = check("G crit >= 1 && fireable(enter)")
    assert not report.valid
    places = [e for e in report.errors if e.code == "unknown_place"]
    transitions = [e for e in report.errors if e.code == "unknown_transition"]
    assert places[0].path == "/ast/args/0/arg/place"
    assert "crit1" in places[0].message
    assert transitions[0].path == "/ast/args/1/transition"
    assert "enter1" in transitions[0].message


def test_an_id_of_the_wrong_kind_is_named():
    report = check("enter1 >= 1")
    assert [e.code for e in report.errors] == ["not_a_place"]
    assert "transition" in report.errors[0].message
    assert [e.code for e in check("fireable(crit1)").errors] == ["not_a_transition"]


def test_compare_terms_are_checked():
    report = check("crit1 + nope <= lock")
    assert report.errors[0].path == "/ast/left/places/1"


def test_operators_must_belong_to_the_logic():
    assert [e.code for e in check("EF crit1 >= 1", logic="ltl").errors] == ["ctl_operator_in_ltl"]
    assert [e.code for e in check("G crit1 >= 1", logic="ctl").errors] == ["ltl_operator_in_ctl"]
    assert [e.code for e in check("F crit1 >= 1", logic="state").errors] == [
        "temporal_operator_in_state_formula"
    ]


def test_next_is_flagged_because_it_limits_reductions():
    report = check("G X crit1 >= 1")
    assert report.uses_next is True
    assert [w.code for w in report.warnings] == ["uses_next"]
    assert "stutter" in report.warnings[0].message
    assert check("AX deadlock").uses_next is True
    assert check("G F deadlock").uses_next is False


def test_cardinality_and_fireability_atoms_are_told_apart():
    mixed = check("crit1 >= 1 && fireable(enter1)")
    assert (mixed.atoms.cardinality, mixed.atoms.fireability) == (True, True)
    assert [w.code for w in mixed.warnings] == ["mixed_atom_classes"]
    assert check("deadlock").atoms.deadlock is True


def test_the_validation_request_takes_a_tree_or_text_but_not_both():
    formula = Formula.model_validate(make_request().formulas[0])
    FormulaValidationRequest(net_id="n", formula=formula)
    FormulaValidationRequest(net_id="n", text="deadlock")
    with pytest.raises(ValidationError):
        FormulaValidationRequest(net_id="n")
    with pytest.raises(ValidationError):
        FormulaValidationRequest(net_id="n", formula=formula, text="deadlock")


def test_two_formulas_cannot_share_an_id():
    with pytest.raises(ValidationError, match="unique"):
        make_request(formulas=[make_request().formulas[0], make_request().formulas[0]])
