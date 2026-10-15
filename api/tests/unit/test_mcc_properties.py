import pytest

from app.domain.errors import InvalidRequestError
from app.domain.formula import And, CtlUnary, CtlUntil, Enabled, LtlUnary, LtlUntil, Not, Or, Tokens
from app.domain.mcc_properties import parse_property_set


def property_set(*, formula, prefix="M-X-"):
    return (
        '<?xml version="1.0"?><property-set xmlns="http://mcc.lip6.fr/">'
        f"<property><id>{prefix}00</id><description>generated</description>"
        f"<formula>{formula}</formula></property></property-set>"
    ).encode()


LE_PLACE = (
    "<integer-le><integer-constant>1</integer-constant>"
    "<tokens-count><place>p1</place></tokens-count></integer-le>"
)
FIRE = "<is-fireable><transition>t1</transition></is-fireable>"
FIRE_SEVERAL = "<is-fireable><transition>t1</transition><transition>t2</transition></is-fireable>"


def only_formula(*, examination, formula):
    return parse_property_set(examination=examination, xml=property_set(formula=formula)).formulas[
        0
    ]


def test_a_reachability_property_is_a_condition_on_a_marking():
    formula = only_formula(
        examination="ReachabilityCardinality",
        formula=f"<exists-path><finally><negation>{LE_PLACE}</negation></finally></exists-path>",
    )
    assert formula.logic == "state"
    assert formula.origin == "mcc"
    assert formula.gloss == "generated"
    assert formula.ast == Not(arg=Tokens(place="p1", cmp=">=", value=1))


def test_an_invariant_keeps_its_temporal_operator():
    formula = only_formula(
        examination="ReachabilityFireability",
        formula=f"<all-paths><globally>{FIRE}</globally></all-paths>",
    )
    assert (formula.logic, formula.ast) == ("ctl", CtlUnary(op="AG", arg=Enabled(transition="t1")))


def test_a_fireability_atom_over_several_transitions_means_any_of_them():
    formula = only_formula(
        examination="CTLFireability", formula=f"<negation>{FIRE_SEVERAL}</negation>"
    )
    assert formula.ast == Not(arg=Or(args=(Enabled(transition="t1"), Enabled(transition="t2"))))


def test_ctl_quantifiers_are_merged_with_their_temporal_operator():
    formula = only_formula(
        examination="CTLCardinality",
        formula=(
            "<exists-path><until><before>" + LE_PLACE + "</before><reach>"
            f"<all-paths><next>{FIRE}</next></all-paths></reach></until></exists-path>"
        ),
    )
    assert formula.logic == "ctl"
    assert isinstance(formula.ast, CtlUntil)
    assert formula.ast.op == "EU"
    assert formula.ast.right == CtlUnary(op="AX", arg=Enabled(transition="t1"))


def test_ltl_drops_the_outer_quantifier_and_uses_ltl_operators():
    formula = only_formula(
        examination="LTLFireability",
        formula=(
            f"<all-paths><conjunction><globally><next>{FIRE}</next></globally>"
            f"<until><before>{FIRE}</before><reach>{FIRE_SEVERAL}</reach></until>"
            "</conjunction></all-paths>"
        ),
    )
    assert formula.logic == "ltl"
    assert isinstance(formula.ast, And)
    assert formula.ast.args[0] == LtlUnary(
        op="G", arg=LtlUnary(op="X", arg=Enabled(transition="t1"))
    )
    assert isinstance(formula.ast.args[1], LtlUntil)


def test_upper_bounds_are_bound_queries_not_formulas():
    parsed = parse_property_set(
        examination="UpperBounds",
        xml=property_set(formula="<place-bound><place>p1</place><place>p2</place></place-bound>"),
    )
    assert parsed.formulas == ()
    assert parsed.bounds[0].places == ("p1", "p2")


@pytest.mark.parametrize(
    ("examination", "formula"),
    [
        ("CTLCardinality", "<globally><true/></globally>"),  # no path quantifier
        ("LTLFireability", f"<exists-path><finally>{FIRE}</finally></exists-path>"),
        ("LTLFireability", "<all-paths><mystery/></all-paths>"),  # never skipped silently
        ("UpperBounds", FIRE),
    ],
)
def test_what_is_not_understood_is_refused_not_skipped(examination, formula):
    with pytest.raises(InvalidRequestError):
        parse_property_set(examination=examination, xml=property_set(formula=formula))


def test_broken_xml_and_entity_bombs_are_refused():
    with pytest.raises(InvalidRequestError):
        parse_property_set(examination="CTLCardinality", xml=b"<property-set>")
    bomb = b'<!DOCTYPE x [<!ENTITY a "aaaa">]><property-set xmlns="http://mcc.lip6.fr/">&a;</property-set>'
    with pytest.raises(InvalidRequestError):
        parse_property_set(examination="CTLCardinality", xml=bomb)


def test_a_property_without_formula_is_refused():
    xml = (
        b'<property-set xmlns="http://mcc.lip6.fr/"><property><id>x</id></property></property-set>'
    )
    with pytest.raises(InvalidRequestError):
        parse_property_set(examination="CTLCardinality", xml=xml)
