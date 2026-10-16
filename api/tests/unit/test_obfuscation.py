import pytest

from app.domain.errors import InvalidRequestError
from app.domain.formula import Formula
from app.domain.formula_text import parse_expression, render_text
from app.domain.net_document import (
    PTNET_TYPE_URI,
    Annotation,
    Arc,
    NetDocument,
    Page,
    Place,
    RefPlace,
    ToolSpecific,
    Transition,
)
from app.domain.net_structure import build_structure
from app.domain.obfuscation import obfuscate_names, restore_formula
from tests.support import MUTEX_DOCUMENT


def test_every_name_is_replaced_and_the_structure_is_the_same():
    result = obfuscate_names(document=MUTEX_DOCUMENT)
    dumped = result.document.model_dump_json()
    for original in ("idle1", "crit1", "lock", "enter1", "leave1", "mutex"):
        assert original not in dumped
    before = build_structure(document=MUTEX_DOCUMENT, net_id="n")
    after = build_structure(document=result.document, net_id="m")
    assert (len(after.places), len(after.transitions), len(after.arcs)) == (3, 2, 6)
    new_of = {r.original: r.obfuscated for r in result.renamings}
    assert {(new_of[a.source], new_of[a.target], a.weight) for a in before.arcs} == {
        (a.source, a.target, a.weight) for a in after.arcs
    }
    assert {new_of[p.id]: p.tokens for p in before.places} == {p.id: p.tokens for p in after.places}
    assert all(p.name == p.id for p in after.places)  # the name the model reads is the new id


def test_the_renaming_is_deterministic_and_numbers_ids_in_sorted_order():
    first = obfuscate_names(document=MUTEX_DOCUMENT)
    assert first == obfuscate_names(document=MUTEX_DOCUMENT)
    places = {r.original: r.obfuscated for r in first.renamings if r.kind == "place"}
    assert places == {"crit1": "p1", "idle1": "p2", "lock": "p3"}


def test_a_property_about_obfuscated_names_is_written_back_with_the_original_ones():
    result = obfuscate_names(document=MUTEX_DOCUMENT)
    new_of = {r.original: r.obfuscated for r in result.renamings}
    text = (
        f"AG (({new_of['crit1']} + {new_of['idle1']} <= 2) && !deadlock && "
        f"EF fireable({new_of['enter1']}) && ({new_of['lock']} >= 1 -> {new_of['crit1']} == 0))"
    )
    formula = Formula(id="f", logic="ctl", ast=parse_expression(text=text), origin="llm", gloss="g")
    restored = restore_formula(formula=formula, renamings=result.renamings)
    shown = render_text(expression=restored.ast)
    assert "crit1 + idle1 <= 2" in shown
    assert "fireable(enter1)" in shown
    assert "lock >= 1 -> crit1 == 0" in shown
    assert restored.gloss == "g"
    assert restored.id == "f"
    assert "p1" not in shown


def test_pages_reference_nodes_tool_data_and_arc_ids_are_renamed_or_dropped():
    document = NetDocument(
        source_id="secret-name",
        type_uri=PTNET_TYPE_URI,
        name=Annotation(text="Dining philosophers"),
        pages=(
            Page(
                id="Philosophers",
                name=Annotation(text="the philosophers page"),
                places=(
                    Place(
                        id="Fork",
                        name=Annotation(text="Fork"),
                        tool_specific=(ToolSpecific(tool="t", version="1"),),
                    ),
                ),
                transitions=(Transition(id="Eat"),),
                arcs=(Arc(id="takes-fork", source="Fork", target="Eat"),),
            ),
            Page(
                id="Table",
                ref_places=(RefPlace(id="ForkRef", ref="Fork"),),
                transitions=(Transition(id="Serve"),),
                arcs=(Arc(id="serve-fork", source="Serve", target="ForkRef"),),
            ),
        ),
    )
    result = obfuscate_names(document=document)
    dumped = result.document.model_dump_json()
    for leaked in (
        "Fork",
        "Eat",
        "Serve",
        "Philosophers",
        "Table",
        "takes-fork",
        "secret",
        "Dining",
    ):
        assert leaked not in dumped
    structure = build_structure(document=result.document, net_id="m")
    assert (len(structure.places), len(structure.transitions), len(structure.arcs)) == (1, 2, 2)


def test_colored_nets_are_refused():
    colored = MUTEX_DOCUMENT.model_copy(
        update={"type_uri": "http://www.pnml.org/version-2009/grammar/symmetricnet"}
    )
    with pytest.raises(InvalidRequestError):
        obfuscate_names(document=colored)
