from app.domain.colored_formulas import translate_expression, translate_formula
from app.domain.contract import Assignment
from app.domain.formula import Formula
from app.domain.formula_text import parse_expression, render_text
from app.domain.operations import Lineage, LineageExpansion, LineagePlace

LINEAGE = Lineage(
    net_id="child",
    parent_id="colored",
    rule="unfold",
    places=(
        LineagePlace(unfolded="pool_1", original="pool"),
        LineagePlace(unfolded="pool_2", original="pool"),
        LineagePlace(unfolded="lone", original="single"),
    ),
    expansions=(
        LineageExpansion(
            transition="pick_1", original=("pick",), binding=(Assignment(variable="x", color="1"),)
        ),
        LineageExpansion(
            transition="pick_2", original=("pick",), binding=(Assignment(variable="x", color="2"),)
        ),
        LineageExpansion(transition="only", original=("once",)),
    ),
)


def translated(text):
    return render_text(
        expression=translate_expression(expression=parse_expression(text=text), lineage=LINEAGE)
    )


def test_the_tokens_of_a_colored_place_are_the_sum_over_its_colors():
    assert translated("pool >= 1") == "pool_1 + pool_2 >= 1"
    assert translated("single == 0") == "lone == 0"  # a place with one color is just renamed


def test_a_colored_transition_is_fireable_when_one_of_its_bindings_is():
    assert translated("EF fireable(pick)") == "EF (fireable(pick_1) || fireable(pick_2))"
    assert translated("AG fireable(once)") == "AG fireable(only)"


def test_comparisons_between_sums_and_the_operators_around_atoms_are_kept():
    assert translated("pool + single <= single") == "pool_1 + pool_2 + lone <= lone"
    assert translated("AG (pool >= 1 -> !deadlock)") == "AG (pool_1 + pool_2 >= 1 -> !deadlock)"


def test_a_citation_that_is_not_a_colored_element_is_left_for_the_unfolded_net_to_judge():
    assert translated("pool_1 >= 1") == "pool_1 >= 1"
    assert translated("ghost >= 1") == "ghost >= 1"


def test_a_net_that_is_not_an_unfolding_has_nothing_to_translate():
    empty = Lineage(net_id="c", parent_id="p", rule="unfold")
    result = translate_expression(expression=parse_expression(text="fireable(pick)"), lineage=empty)
    assert render_text(expression=result) == "fireable(pick)"


def test_the_formula_keeps_its_identity():
    formula = Formula(
        id="f", logic="ctl", gloss="g", origin="llm", ast=parse_expression(text="EF pool >= 1")
    )
    moved = translate_formula(formula=formula, lineage=LINEAGE)
    assert (moved.id, moved.logic, moved.gloss, moved.origin) == ("f", "ctl", "g", "llm")
    assert moved.ast != formula.ast
