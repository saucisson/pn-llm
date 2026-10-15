import json

import pytest

from app.domain.canonical import canonical_bytes, canonical_json, canonical_number, net_id_of
from app.domain.errors import InvalidNetError
from app.domain.net_document import (
    PTNET_TYPE_URI,
    Annotation,
    Arc,
    NetDocument,
    Page,
    Place,
    RefPlace,
    RefTransition,
    Transition,
    XmlAttribute,
    XmlNode,
)
from app.domain.net_validation import DocumentLimits, parse_document, validate_document

LIMITS = DocumentLimits()


def text(*, value: str) -> Annotation:
    return Annotation(text=value)


def mutex(*, shuffled: bool = False, version_marking: str = "1") -> NetDocument:
    places = (
        Place(id="idle1", name=text(value="idle1"), initial_marking=text(value=version_marking)),
        Place(id="crit1", name=text(value="crit1")),
    )
    transitions = (Transition(id="enter1", name=text(value="enter1")), Transition(id="leave1"))
    arcs = (
        Arc(id="a1", source="idle1", target="enter1"),
        Arc(id="a2", source="enter1", target="crit1", inscription=text(value="2")),
        Arc(id="a3", source="crit1", target="leave1"),
        Arc(id="a4", source="leave1", target="idle1"),
    )
    if shuffled:
        places, transitions, arcs = places[::-1], transitions[::-1], arcs[::-1]
    return NetDocument(
        source_id="mutex",
        type_uri=PTNET_TYPE_URI,
        places=places,
        transitions=transitions,
        arcs=arcs,
    )


def test_golden_hash_of_a_fixed_net():
    """A stored id never changes: update this only with a migration (ADR 0015)."""
    assert net_id_of(document=mutex()) == "e191a9b285370ea9780f5939e8a0858a"


def test_permuting_elements_keeps_the_id():
    assert net_id_of(document=mutex(shuffled=True)) == net_id_of(document=mutex())


def test_changing_a_marking_changes_the_id():
    assert net_id_of(document=mutex(version_marking="2")) != net_id_of(document=mutex())


def test_renaming_changes_the_id():
    renamed = mutex().model_copy(update={"places": (Place(id="idle1", name=text(value="Idle1")),)})
    assert net_id_of(document=renamed) != net_id_of(document=mutex())


def test_schema_version_is_not_hashed_and_defaults_are_omitted():
    canonical = json.loads(canonical_bytes(document=mutex()))
    assert "schema_version" not in canonical
    assert canonical["kind"] == "pt"
    assert "tool_specific" not in canonical["places"][0]


def test_attribute_order_is_lexical():
    first = XmlNode(
        name="n", attributes=(XmlAttribute(name="b", value="1"), XmlAttribute(name="a", value="2"))
    )
    second = XmlNode(
        name="n", attributes=(XmlAttribute(name="a", value="2"), XmlAttribute(name="b", value="1"))
    )
    assert first == second


def test_an_attribute_name_cannot_repeat():
    with pytest.raises(ValueError, match="twice"):
        XmlNode(
            name="n",
            attributes=(XmlAttribute(name="a", value="1"), XmlAttribute(name="a", value="2")),
        )


def test_nested_pages_are_canonicalized_recursively():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        pages=(
            Page(id="z", places=(Place(id="p2"), Place(id="p1"))),
            Page(id="a"),
        ),
    )
    ordered = document.sorted_by_id()
    assert [page.id for page in ordered.pages] == ["a", "z"]
    assert [place.id for place in ordered.pages[1].places] == ["p1", "p2"]


@pytest.mark.parametrize(
    ("type_uri", "kind"),
    [
        ("http://www.pnml.org/version-2009/grammar/ptnet", "pt"),
        ("http://www.pnml.org/version-2009/grammar/symmetricnet", "symmetric"),
        ("http://www.pnml.org/version-2009/grammar/highlevelnet", "hlpn"),
        ("http://www.pnml.org/version-2009/grammar/pnmlcoremodel", "core"),
        ("urn:other", "other"),
    ],
)
def test_kind_is_derived_from_the_type_uri(type_uri, kind):
    assert NetDocument(source_id="n", type_uri=type_uri).kind == kind


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "1"),
        (-0.0, "0"),
        (2.5, "2.5"),
        (1e-7, "1e-7"),
        (1e21, "1e+21"),
        (123456789.125, "123456789.125"),
    ],
)
def test_numbers_follow_ecmascript(value, expected):
    assert canonical_number(value=value) == expected


def test_non_finite_numbers_have_no_canonical_form():
    with pytest.raises(ValueError, match="non-finite"):
        canonical_number(value=float("inf"))


def test_keys_are_sorted_by_utf16_code_units():
    # U+E000 sorts before U+10000 in code points but after it in UTF-16 (surrogates start at D800).
    value = {chr(0xE000): 2, chr(0x10000): 1}
    assert canonical_json(value=value) == '{"' + chr(0x10000) + '":1,"' + chr(0xE000) + '":2}'
    assert canonical_json(value={"b": [True, None, "é"], "a": {}}) == '{"a":{},"b":[true,null,"é"]}'


def test_json_round_trip_is_a_fixed_point():
    document = mutex()
    reread = parse_document(payload=document.model_dump_json().encode(), limits=LIMITS)
    assert net_id_of(document=reread) == net_id_of(document=document)


def test_a_valid_net_passes_validation():
    validate_document(document=mutex(), limits=LIMITS)


def fault_of(*, document: NetDocument, limits: DocumentLimits = LIMITS) -> InvalidNetError:
    with pytest.raises(InvalidNetError) as caught:
        validate_document(document=document, limits=limits)
    return caught.value


def test_duplicate_ids_are_refused_across_kinds():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="x"),),
        transitions=(Transition(id="x"),),
    )
    assert "duplicate id" in str(fault_of(document=document))
    assert fault_of(document=document).location == "/transitions/0/id"


def test_a_page_id_cannot_collide_with_an_element():
    document = NetDocument(
        source_id="n", type_uri=PTNET_TYPE_URI, places=(Place(id="x"),), pages=(Page(id="x"),)
    )
    assert fault_of(document=document).location == "/pages/0/id"


def test_dangling_arc_is_located():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p"),),
        arcs=(Arc(id="a", source="p", target="nowhere"),),
    )
    assert fault_of(document=document).location == "/arcs/0/target"


def test_arc_between_two_places_is_refused():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p"), Place(id="q")),
        arcs=(Arc(id="a", source="p", target="q"),),
    )
    assert "place and a transition" in str(fault_of(document=document))


def test_arcs_may_join_reference_nodes_across_pages():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        pages=(
            Page(id="one", places=(Place(id="p"),)),
            Page(
                id="two",
                transitions=(Transition(id="t"),),
                ref_places=(RefPlace(id="rp", ref="p"),),
                arcs=(Arc(id="a", source="rp", target="t"),),
            ),
        ),
    )
    validate_document(document=document, limits=LIMITS)


def test_reference_must_resolve_to_the_same_kind():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p"),),
        ref_transitions=(RefTransition(id="rt", ref="p"),),
    )
    assert fault_of(document=document).location == "/ref_transitions/0/ref"


def test_reference_cycle_is_refused():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        ref_places=(RefPlace(id="a", ref="b"), RefPlace(id="b", ref="a")),
    )
    assert "cycle" in str(fault_of(document=document))


def test_reference_chain_resolves():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p"),),
        ref_places=(RefPlace(id="a", ref="b"), RefPlace(id="b", ref="p")),
    )
    validate_document(document=document, limits=LIMITS)


@pytest.mark.parametrize("marking", ["x", "-1", "1.5", "", "٣"])
def test_pt_markings_must_be_non_negative_integers(marking):
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p", initial_marking=text(value=marking)),),
    )
    assert fault_of(document=document).location == "/places/0/initial_marking/text"


@pytest.mark.parametrize("inscription", ["0", "a", "-2"])
def test_pt_inscriptions_must_be_positive_integers(inscription):
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p"),),
        transitions=(Transition(id="t"),),
        arcs=(Arc(id="a", source="p", target="t", inscription=text(value=inscription)),),
    )
    assert fault_of(document=document).location == "/arcs/0/inscription/text"


def test_colored_markings_are_not_parsed_as_integers():
    document = NetDocument(
        source_id="n",
        type_uri="http://www.pnml.org/version-2009/grammar/symmetricnet",
        places=(Place(id="p", initial_marking=text(value="1`dot")),),
    )
    validate_document(document=document, limits=LIMITS)


def test_size_bounds_are_enforced():
    nested = NetDocument(
        source_id="n", type_uri=PTNET_TYPE_URI, pages=(Page(id="a", pages=(Page(id="b"),)),)
    )
    assert "deeply" in str(fault_of(document=nested, limits=DocumentLimits(max_page_depth=2)))
    many = NetDocument(
        source_id="n", type_uri=PTNET_TYPE_URI, places=(Place(id="a"), Place(id="b"))
    )
    assert "too many" in str(fault_of(document=many, limits=DocumentLimits(max_elements=1)))
    long = NetDocument(source_id="n", type_uri=PTNET_TYPE_URI, places=(Place(id="abc"),))
    assert "too long" in str(fault_of(document=long, limits=DocumentLimits(max_string_length=2)))


def test_parse_document_reports_a_json_pointer():
    with pytest.raises(InvalidNetError) as caught:
        parse_document(
            payload=b'{"source_id": "n", "type_uri": "u", "places": [{"id": 3}]}', limits=LIMITS
        )
    assert caught.value.location == "/places/0/id"


def test_parse_document_refuses_garbage():
    with pytest.raises(InvalidNetError):
        parse_document(payload=b"not json", limits=LIMITS)
