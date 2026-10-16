from pathlib import Path

import pytest

from app.domain.colored import UnsupportedColoredError
from app.domain.net_structure import build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml
from app.domain.unfolding import UnfoldingTooLargeError, UnfoldLimits, unfold
from tests.support import MUTEX_DOCUMENT

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "colored"


def load(name):
    return import_pnml(payload=(CORPUS / name).read_bytes(), limits=DocumentLimits())


def unfolded(name, **limits):
    return unfold(document=load(name), net_id="n", limits=UnfoldLimits(**limits))


def structure_of(result):
    return build_structure(document=result.document, net_id="u")


def test_the_guarded_net_unfolds_to_the_bindings_its_guard_allows():
    result = unfolded("guarded.pnml")
    structure = structure_of(result)
    # Two places over three colors; the guard x != y and not (x < succ(y)) keeps some pairs.
    assert {p.id for p in structure.places} == {
        f"{place}_{c}" for place in ("pool", "pairs") for c in "123"
    }
    assert {p.id: p.tokens for p in structure.places if p.id.startswith("pool")} == {
        "pool_1": 1,
        "pool_2": 1,
        "pool_3": 1,
    }
    # x != y and x >= succ(y) over the cyclic order 1<2<3: succ(1)=2, succ(2)=3, succ(3)=1.
    # y=1: x in {2,3}; y=2: x=3; y=3 (succ is 1, so any x but 3): x in {1,2}.
    bindings = {tuple((a.variable, a.color) for a in t.binding) for t in result.mapping.transitions}
    assert bindings == {
        (("x", "3"), ("y", "1")),
        (("x", "3"), ("y", "2")),
        (("x", "2"), ("y", "1")),
        (("x", "1"), ("y", "3")),
        (("x", "2"), ("y", "3")),
    }
    # The pair (x=2, y=1) consumes one token of pool_2 and one of pool_1, puts two in pairs_2.
    (pick,) = [
        t
        for t in result.mapping.transitions
        if {(a.variable, a.color) for a in t.binding} == {("x", "2"), ("y", "1")}
    ]
    arcs = [
        (a.source, a.target, a.weight)
        for a in structure.arcs
        if pick.unfolded in {a.source, a.target}
    ]
    assert sorted(arcs) == sorted(
        [("pool_2", pick.unfolded, 1), ("pool_1", pick.unfolded, 1), (pick.unfolded, "pairs_2", 2)]
    )


def test_a_place_over_a_single_value_keeps_its_name_and_the_mapping_names_every_color():
    result = unfolded("DatabaseWithMutex-COL-02.pnml")
    assert len(result.mapping.places) == len(structure_of(result).places)
    colors = {(p.original, p.color) for p in result.mapping.places}
    assert len(colors) == len(result.mapping.places)  # no two unfolded places for one color
    ids = [t.unfolded for t in result.mapping.transitions]
    assert len(set(ids)) == len(ids)


def test_the_philosophers_unfold_to_the_known_p_t_shape():
    result = unfolded("Philosophers-COL-000100.pnml")
    structure = structure_of(result)
    # One token per philosopher thinking and per fork, none eating.
    marked = {p.id: p.tokens for p in structure.places if p.tokens}
    assert len(marked) == 200
    assert set(marked.values()) == {1}
    assert len(structure.places) == 500
    assert len(structure.transitions) == 500


def test_the_unfolded_net_is_a_valid_p_t_net_with_consistent_arcs():
    for name in ("guarded.pnml", "DatabaseWithMutex-COL-02.pnml", "FileSystem-COL-N02I10B08.pnml"):
        result = unfolded(name)
        structure = structure_of(result)
        node_ids = {n.id for n in (*structure.places, *structure.transitions)}
        assert all(a.source in node_ids and a.target in node_ids for a in structure.arcs)
        assert all(a.weight and a.weight > 0 for a in structure.arcs)
        assert result.document.kind == "pt"


def test_the_limits_stop_an_unfolding_that_explodes_with_a_clear_error():
    with pytest.raises(UnfoldingTooLargeError, match="places"):
        unfolded("Philosophers-COL-000100.pnml", max_places=10)
    with pytest.raises(UnfoldingTooLargeError, match=r"transitions|bindings"):
        unfolded("FileSystem-COL-N02I10B08.pnml", max_transitions=5)
    with pytest.raises(UnfoldingTooLargeError, match="arcs"):
        unfolded("guarded.pnml", max_arcs=2)


def test_only_symmetric_nets_can_be_unfolded():
    with pytest.raises(UnsupportedColoredError, match="symmetric"):
        unfold(document=MUTEX_DOCUMENT, net_id="n", limits=UnfoldLimits())


def test_the_contest_gcd_model_unfolds_with_ranges_products_and_successors():
    path = (
        Path(__file__).resolve().parents[1] / "corpus" / "mcc" / "PGCD-COL-D04N050" / "model.pnml"
    )
    document = import_pnml(payload=path.read_bytes(), limits=DocumentLimits())
    result = unfold(document=document, net_id="n", limits=UnfoldLimits())
    assert (len(result.mapping.places), len(result.mapping.transitions)) == (15, 15)


SORTS = """
<namedsort id="R" name="R"><finiteintrange start="1" end="3"/></namedsort>
<namedsort id="E" name="E"><finiteenumeration>
  <feconstant id="a" name="a"/><feconstant id="b" name="b"/></finiteenumeration></namedsort>
<namedsort id="P" name="P"><productsort>
  <usersort declaration="R"/><usersort declaration="E"/></productsort></namedsort>
<variabledecl id="n" name="n"><usersort declaration="R"/></variabledecl>
<variabledecl id="e" name="e"><usersort declaration="E"/></variabledecl>
"""


def term(*, text):
    return f"<hlinscription><structure>{text}</structure></hlinscription>"


def var(name):
    return f'<variable refvariable="{name}"/>'


def sub(inner):
    return f"<subterm>{inner}</subterm>"


def number(count):
    return '<numberconstant value="' + str(count) + '"><positive/></numberconstant>'


def numberof(count, inner):
    return "<numberof>" + sub(number(count)) + sub(inner) + "</numberof>"


def small(*, places, transitions, arcs, sorts=SORTS):
    body = []
    for pid, sort, marking in places:
        initial = (
            f"<hlinitialMarking><structure>{marking}</structure></hlinitialMarking>"
            if marking
            else ""
        )
        body.append(
            f'<place id="{pid}"><name><text>{pid}</text></name><type><structure>'
            f'<usersort declaration="{sort}"/></structure></type>{initial}</place>'
        )
    for tid, guard in transitions:
        condition = f"<condition><structure>{guard}</structure></condition>" if guard else ""
        body.append(
            f'<transition id="{tid}"><name><text>{tid}</text></name>{condition}</transition>'
        )
    for index, (source, target, text) in enumerate(arcs):
        body.append(
            f'<arc id="a{index}" source="{source}" target="{target}">{term(text=text)}</arc>'
        )
    xml = (
        '<pnml><net id="n" type="http://www.pnml.org/version-2009/grammar/symmetricnet">'
        f"<declaration><structure><declarations>{sorts}</declarations></structure></declaration>"
        f'<page id="pg">{"".join(body)}</page></net></pnml>'
    )
    return import_pnml(payload=xml.encode(), limits=DocumentLimits())


def test_the_successor_past_the_end_of_a_range_leaves_that_binding_out():
    document = small(
        places=[
            ("p", "R", numberof(1, '<all><usersort declaration="R"/></all>')),
            ("q", "R", None),
        ],
        transitions=[("t", None)],
        arcs=[
            ("p", "t", numberof(1, var("n"))),
            ("t", "q", numberof(1, f"<successor>{sub(var('n'))}</successor>")),
        ],
    )
    result = unfold(document=document, net_id="n", limits=UnfoldLimits())
    assert sorted(a.color for t in result.mapping.transitions for a in t.binding) == ["1", "2"]


def test_the_successor_in_a_non_cyclic_enumeration_stops_at_the_last_value():
    document = small(
        places=[
            ("p", "E", numberof(1, '<all><usersort declaration="E"/></all>')),
            ("q", "E", None),
        ],
        transitions=[("t", None)],
        arcs=[
            ("p", "t", numberof(1, var("e"))),
            ("t", "q", numberof(1, f"<successor>{sub(var('e'))}</successor>")),
        ],
    )
    result = unfold(document=document, net_id="n", limits=UnfoldLimits())
    assert [a.color for t in result.mapping.transitions for a in t.binding] == ["a"]


def test_a_product_sort_has_a_place_per_tuple_named_by_its_parts():
    document = small(places=[("p", "P", None)], transitions=[], arcs=[])
    result = unfold(document=document, net_id="n", limits=UnfoldLimits())
    assert sorted(p.unfolded for p in result.mapping.places) == [
        "p_1.a",
        "p_1.b",
        "p_2.a",
        "p_2.b",
        "p_3.a",
        "p_3.b",
    ]


def test_a_subtraction_that_goes_below_zero_and_an_undeclared_variable_are_refused():
    below = small(
        places=[("p", "R", numberof(1, '<all><usersort declaration="R"/></all>'))],
        transitions=[("t", None)],
        arcs=[
            (
                "p",
                "t",
                f"<subtract>{sub(numberof(1, var('n')))}{sub(numberof(2, var('n')))}</subtract>",
            )
        ],
    )
    with pytest.raises(UnsupportedColoredError, match="below zero"):
        unfold(document=below, net_id="n", limits=UnfoldLimits())
    unknown = small(
        places=[("p", "R", None)],
        transitions=[("t", None)],
        arcs=[("p", "t", numberof(1, var("ghost")))],
    )
    with pytest.raises(UnsupportedColoredError, match="undeclared variable"):
        unfold(document=unknown, net_id="n", limits=UnfoldLimits())


def test_an_inscription_yielding_a_value_outside_the_sort_of_its_place_is_refused():
    wrong = small(
        places=[("p", "R", None), ("q", "E", None)],
        transitions=[("t", None)],
        arcs=[("p", "t", numberof(1, var("n"))), ("t", "q", numberof(1, var("n")))],
    )
    with pytest.raises(UnsupportedColoredError, match="outside the sort"):
        unfold(document=wrong, net_id="n", limits=UnfoldLimits())


def test_ordered_comparisons_on_ranges_and_a_missing_inscription():
    guard = "<lessthan>" + sub(var("n")) + sub(number(2)) + "</lessthan>"
    ranged = small(
        places=[("p", "R", numberof(1, '<all><usersort declaration="R"/></all>'))],
        transitions=[("t", guard)],
        arcs=[("p", "t", numberof(1, var("n")))],
    )
    result = unfold(document=ranged, net_id="n", limits=UnfoldLimits())
    assert [a.color for t in result.mapping.transitions for a in t.binding] == ["1"]
