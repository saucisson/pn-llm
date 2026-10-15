import random

import pytest

from app.domain.errors import FormulaSyntaxError
from app.domain.formula import (
    And,
    Compare,
    Constant,
    CtlUnary,
    CtlUntil,
    Deadlock,
    Enabled,
    Implies,
    LtlUnary,
    LtlUntil,
    Not,
    Or,
    TokenCount,
    Tokens,
    Truth,
)
from app.domain.formula_text import (
    formula_from_text,
    parse_expression,
    quote_id,
    render_text,
    tokenize,
)


def tokens(place, cmp=">=", value=1):
    return Tokens(place=place, cmp=cmp, value=value)


def test_mutual_exclusion_in_ltl():
    parsed = parse_expression(text="G !(crit1 >= 1 && crit2 >= 1)")
    assert parsed == LtlUnary(op="G", arg=Not(arg=And(args=(tokens("crit1"), tokens("crit2")))))


def test_precedence_of_connectives():
    parsed = parse_expression(text="a >= 1 || b >= 1 && c >= 1 -> d >= 1")
    assert parsed == Implies(
        left=Or(args=(tokens("a"), And(args=(tokens("b"), tokens("c"))))), right=tokens("d")
    )


def test_implication_is_right_associative():
    parsed = parse_expression(text="a >= 1 -> b >= 1 -> c >= 1")
    assert parsed == Implies(left=tokens("a"), right=Implies(left=tokens("b"), right=tokens("c")))


def test_chains_of_the_same_connective_are_flattened():
    assert parse_expression(text="a >= 1 && b >= 1 && c >= 1") == And(
        args=(tokens("a"), tokens("b"), tokens("c"))
    )
    assert parse_expression(text="a >= 1 && (b >= 1 && c >= 1)") == And(
        args=(tokens("a"), And(args=(tokens("b"), tokens("c"))))
    )


def test_ltl_until_and_nested_temporal_operators():
    assert parse_expression(text="G F x >= 1") == LtlUnary(
        op="G", arg=LtlUnary(op="F", arg=tokens("x"))
    )
    assert parse_expression(text="a >= 1 U b >= 1") == LtlUntil(left=tokens("a"), right=tokens("b"))


def test_ctl_operators_and_bracketed_until():
    assert parse_expression(text="AG EF deadlock") == CtlUnary(
        op="AG", arg=CtlUnary(op="EF", arg=Deadlock())
    )
    assert parse_expression(text="A[a >= 1 U b >= 1]") == CtlUntil(
        op="AU", left=tokens("a"), right=tokens("b")
    )
    assert parse_expression(text="E[ true U fireable(t) ]") == CtlUntil(
        op="EU", left=Truth(value=True), right=Enabled(transition="t")
    )


def test_fireability_and_the_mcc_form():
    assert parse_expression(text="fireable(t1)") == Enabled(transition="t1")
    assert parse_expression(text="is-fireable(t1, t2)") == Or(
        args=(Enabled(transition="t1"), Enabled(transition="t2"))
    )


def test_comparisons_of_places_and_constants():
    assert parse_expression(text="p = 2") == tokens("p", "==", 2)
    assert parse_expression(text="p1 + p2 <= p3") == Compare(
        left=TokenCount(places=("p1", "p2")), cmp="<=", right=TokenCount(places=("p3",))
    )
    assert parse_expression(text="3 < p") == Compare(
        left=Constant(value=3), cmp="<", right=TokenCount(places=("p",))
    )


def test_ids_with_dashes_and_quotes():
    assert parse_expression(text="p-1 >= 1").place == "p-1"
    assert parse_expression(text='"my place" >= 1').place == "my place"
    assert parse_expression(text='"G" >= 1').place == "G"
    assert parse_expression(text='"12" >= 1').place == "12"
    assert parse_expression(text='"a\\"b\\\\c" >= 1').place == 'a"b\\c'
    assert [t.value for t in tokenize(text="a->b")[:3]] == ["a", "->", "b"]  # not one id


@pytest.mark.parametrize(
    ("text", "position"),
    [
        ("", 0),
        ("G", 1),
        ("a >=", 4),
        ("a >= 1 &&", 9),
        ("(a >= 1", 7),
        ("a >= 1 )", 7),
        ("a ~ 1", 2),
        ("A[a >= 1 b >= 1]", 9),
        ("fireable()", 9),
        ("fireable(12)", 9),
        ("p", 1),
        ('"unterminated >= 1', 0),
    ],
)
def test_syntax_errors_locate_the_fault(text, position):
    with pytest.raises(FormulaSyntaxError) as caught:
        parse_expression(text=text)
    assert caught.value.position == position


def test_tokenize_ends_with_an_end_token():
    assert tokenize(text="  p ")[-1].kind == "END"


def test_logic_is_inferred_from_the_operators():
    kwargs = {"formula_id": "f", "gloss": "", "origin": "user"}
    assert formula_from_text(text="G p >= 1", logic=None, **kwargs).logic == "ltl"
    assert formula_from_text(text="EF p >= 1", logic=None, **kwargs).logic == "ctl"
    assert formula_from_text(text="p >= 1", logic=None, **kwargs).logic == "state"
    assert formula_from_text(text="p >= 1", logic="ltl", **kwargs).logic == "ltl"
    with pytest.raises(FormulaSyntaxError, match="mixes"):
        formula_from_text(text="G EF p >= 1", logic=None, **kwargs)


def test_quote_id_is_the_inverse_of_reading_an_id():
    for name in [
        "plain",
        "with-dash",
        "G",
        "123",
        "has space",
        'q"uote',
        "back\\slash",
        "",
        "a->b",
    ]:
        assert parse_expression(text=f"{quote_id(name=name)} >= 1").place == name


def random_expression(*, rng, depth):
    """Build a random tree of the formula language, to test that printing reads back."""
    if depth == 0 or rng.random() < 0.25:
        return rng.choice(
            [
                tokens(
                    rng.choice(["p", "q-1", "G", "my place"]),
                    rng.choice(["<", ">=", "!="]),
                    rng.randint(0, 9),
                ),
                Compare(left=TokenCount(places=("p", "q")), cmp="<=", right=Constant(value=3)),
                Enabled(transition=rng.choice(["t", "u v"])),
                Deadlock(),
                Truth(value=rng.random() < 0.5),
            ]
        )

    def sub():
        return random_expression(rng=rng, depth=depth - 1)

    builders = {
        "not": lambda: Not(arg=sub()),
        "and": lambda: And(args=tuple(sub() for _ in range(rng.randint(2, 3)))),
        "or": lambda: Or(args=tuple(sub() for _ in range(rng.randint(2, 3)))),
        "implies": lambda: Implies(left=sub(), right=sub()),
        "ltl": lambda: LtlUnary(op=rng.choice(["G", "F", "X"]), arg=sub()),
        "ltlu": lambda: LtlUntil(left=sub(), right=sub()),
        "ctl": lambda: CtlUnary(op=rng.choice(["AG", "AF", "AX", "EG", "EF", "EX"]), arg=sub()),
        "ctlu": lambda: CtlUntil(op=rng.choice(["AU", "EU"]), left=sub(), right=sub()),
    }
    return builders[rng.choice(sorted(builders))]()


def test_printing_then_parsing_gives_back_the_same_tree():
    rng = random.Random(20261015)  # noqa: S311 - reproducible test data, not cryptography
    for _ in range(500):
        expression = random_expression(rng=rng, depth=4)
        text = render_text(expression=expression)
        assert parse_expression(text=text) == expression, text
