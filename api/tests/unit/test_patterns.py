import pytest

from app.domain.errors import FormulaSyntaxError, InvalidRequestError
from app.domain.formula_text import parse_expression, render_text
from app.domain.patterns import PATTERNS, PatternRequest, instantiate


def build(pattern, logic="ctl", **parameters):
    formula = instantiate(
        request=PatternRequest(pattern=pattern, logic=logic, **parameters), formula_id="f"
    )
    return render_text(expression=formula.ast), formula


@pytest.mark.parametrize(
    ("pattern", "logic", "parameters", "text"),
    [
        ("absence", "ctl", {"p": '"a" >= 2'}, "AG !(a >= 2)"),
        ("absence", "ltl", {"p": '"a" >= 2'}, "G !(a >= 2)"),
        ("universality", "ctl", {"p": '"a" <= 1'}, "AG (a <= 1)"),
        ("existence", "ctl", {"p": '"a" >= 1'}, "EF (a >= 1)"),
        ("existence", "ltl", {"p": '"a" >= 1'}, "F (a >= 1)"),
        ("bound", "ctl", {"p": '"a" >= 0', "k": 3}, "AG (a <= 3)"),
        ("response", "ctl", {"p": '"a" >= 1', "q": '"b" >= 1'}, "AG (a >= 1 -> AF (b >= 1))"),
        ("response", "ltl", {"p": '"a" >= 1', "q": '"b" >= 1'}, "G (a >= 1 -> F (b >= 1))"),
        ("exclusion", "ctl", {"p": '"a" >= 1', "q": '"b" >= 1'}, "AG !(a >= 1 && b >= 1)"),
        ("recurrence", "ltl", {"p": '"a" >= 1'}, "G (F (a >= 1))"),
    ],
)
def test_a_pattern_gives_the_formula_the_literature_gives(pattern, logic, parameters, text):
    written, formula = build(pattern, logic, **parameters)
    assert formula.logic == logic
    assert formula.origin == "template"
    assert formula.gloss
    assert formula.ast == parse_expression(text=text)
    assert parse_expression(text=written) == formula.ast  # the text the model sees reads back


def test_precedence_is_the_weak_until_in_each_logic():
    ctl, _ = build("precedence", "ctl", p='"a" >= 1', q='"b" >= 1')
    ltl, _ = build("precedence", "ltl", p='"a" >= 1', q='"b" >= 1')
    assert parse_expression(text=ctl) == parse_expression(
        text="!E[!(b >= 1) U (a >= 1 && !(b >= 1))]"
    )
    assert parse_expression(text=ltl) == parse_expression(
        text="(!(a >= 1) U (b >= 1)) || G !(a >= 1)"
    )


def test_every_pattern_is_listed_and_instantiable():
    parameters = {"p": '"a" >= 1', "q": '"b" >= 1', "k": 2}
    for info in PATTERNS:
        given = {name: parameters[name] for name in info.parameters}
        if info.name == "bound":
            given["p"] = '"a" >= 0'
        formula = instantiate(request=PatternRequest(pattern=info.name, **given), formula_id="x")
        assert formula.id == "x"


def test_missing_parameters_and_temporal_conditions_are_refused_with_the_reason():
    with pytest.raises(InvalidRequestError, match="needs the parameter q"):
        build("response", p='"a" >= 1')
    with pytest.raises(InvalidRequestError, match="needs the parameter k"):
        build("bound", p='"a" >= 0')
    with pytest.raises(InvalidRequestError, match="temporal"):
        build("absence", p='EF "a" >= 1')
    with pytest.raises(InvalidRequestError, match="one place"):
        build("bound", p='"a" >= 1 && "b" >= 1', k=1)
    with pytest.raises(FormulaSyntaxError):
        build("absence", p="a >=")
