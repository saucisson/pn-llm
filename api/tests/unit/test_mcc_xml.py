from pathlib import Path

import pytest

from app.domain.errors import InvalidRequestError
from app.domain.formula import Compare, Constant, Formula, Implies, TokenCount, Tokens
from app.domain.formula_text import formula_from_text
from app.domain.mcc_properties import EXAMINATIONS, parse_property_set
from app.domain.mcc_xml import render_property_set

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "mcc"
INSTANCES = sorted(path.name for path in CORPUS.iterdir() if path.is_dir())
BOOLEAN = tuple(e for e in EXAMINATIONS if e != "UpperBounds")


@pytest.mark.parametrize("instance", INSTANCES)
@pytest.mark.parametrize("examination", BOOLEAN)
def test_contest_formulas_written_then_read_are_unchanged(instance, examination):
    formulas = parse_property_set(
        examination=examination, xml=(CORPUS / instance / f"{examination}.xml").read_bytes()
    ).formulas
    written = render_property_set(formulas=formulas)
    again = parse_property_set(examination=examination, xml=written.encode()).formulas
    assert again == formulas


def one(*, text, logic=None):
    return formula_from_text(
        text=text, formula_id="f<1>", logic=logic, gloss="a & b", origin="user"
    )


def test_other_comparisons_use_less_or_equal_and_a_negation():
    xml = render_property_set(formulas=(one(text='"p" < 2'),))
    assert "<negation><integer-le><integer-constant>2</integer-constant>" in xml
    assert "<id>f&lt;1&gt;</id>" in xml
    assert "<description>a &amp; b</description>" in xml
    equal = render_property_set(formulas=(one(text='"p" == 2'),))
    assert equal.count("<integer-le>") == 2
    different = render_property_set(formulas=(one(text='"p" != 2'),))
    assert "<negation><conjunction>" in different


def test_deadlock_truth_implication_and_term_comparison_have_their_elements():
    xml = render_property_set(
        formulas=(
            Formula(
                id="a",
                logic="state",
                ast=Implies(
                    left=Tokens(place="p", cmp="<=", value=1),
                    right=Compare(
                        left=TokenCount(places=("p", "q")), cmp=">", right=Constant(value=3)
                    ),
                ),
            ),
            one(text="deadlock"),
            one(text="true"),
            one(text="false"),
        )
    )
    assert "<deadlock/>" in xml
    assert "<true/>" in xml
    assert "<false/>" in xml
    assert xml.count("<disjunction><negation><integer-le>") == 1
    assert "<tokens-count><place>p</place><place>q</place></tokens-count>" in xml


def test_semantics_of_the_state_and_ltl_wrappers():
    state = render_property_set(formulas=(one(text='"p" >= 1', logic="state"),))
    assert "<formula><exists-path><finally>" in state
    ltl = render_property_set(formulas=(one(text='F "p" >= 1'),))
    assert "<formula><all-paths><finally>" in ltl


def test_no_formula_is_refused():
    with pytest.raises(InvalidRequestError):
        render_property_set(formulas=())
