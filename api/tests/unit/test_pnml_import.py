import pytest

from app.domain.canonical import net_id_of
from app.domain.errors import PnmlError
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml
from tests.support import MUTEX_PNML

LIMITS = DocumentLimits()

RICH = b"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
 <net id="rich" type="http://www.pnml.org/version-2009/grammar/ptnet" extra="1">
  <name><text>Rich net</text></name>
  <toolspecific tool="example" version="1.0"><note>kept <b>as</b> is</note></toolspecific>
  <page id="main">
   <place id="p1">
    <name><text>p one</text><graphics><offset x="-10" y="20.5"/></graphics></name>
    <initialMarking><text>2</text></initialMarking>
    <graphics><position x="40" y="60"/><dimension x="20" y="20"/><fill color="red"/></graphics>
   </place>
   <referenceTransition id="rt" ref="t1"/>
   <arc id="a1" source="p1" target="rt">
    <inscription><text>3</text></inscription>
    <graphics><position x="1" y="2"/><position x="3" y="4"/><line width="2"/></graphics>
   </arc>
   <page id="inner"><transition id="t1"><name><text>t1</text></name></transition></page>
  </page>
  <unknownThing a="b"><child/></unknownThing>
 </net>
</pnml>"""


def test_mutex_is_imported_with_names_and_ids_as_written():
    document = import_pnml(payload=MUTEX_PNML, limits=LIMITS)
    assert document.source_id == "mutex"
    assert document.kind == "pt"
    page = document.pages[0]
    assert [place.id for place in page.places] == ["idle1", "crit1", "lock"]
    assert page.places[0].name is not None
    assert page.places[0].name.text == "idle1"
    assert page.places[0].initial_marking is not None
    assert page.places[0].initial_marking.text == "1"
    assert len(page.arcs) == 6
    assert not page.extensions
    assert not document.extensions


def test_everything_is_kept():
    document = import_pnml(payload=RICH, limits=LIMITS)
    assert document.name is not None
    assert document.name.text == "Rich net"
    assert document.tool_specific[0].tool == "example"
    note = document.tool_specific[0].content[0]
    assert note.name.endswith("}note")  # type: ignore[union-attr]
    assert note.content[0] == "kept "  # type: ignore[union-attr]
    assert document.extra_attributes[0].name == "extra"
    assert document.extensions[0].name.endswith("}unknownThing")
    main = document.pages[0]
    place = main.places[0]
    assert place.graphics is not None
    assert place.graphics.position is not None
    assert place.graphics.position.x == 40
    assert place.graphics.fill is not None
    assert place.graphics.fill.color == "red"
    assert place.name is not None
    assert place.name.graphics is not None
    assert place.name.graphics.offset is not None
    assert place.name.graphics.offset.y == 20.5
    assert main.arcs[0].graphics is not None
    assert len(main.arcs[0].graphics.positions) == 2
    assert main.ref_transitions[0].ref == "t1"
    assert main.pages[0].transitions[0].id == "t1"


def test_namespace_declarations_do_not_change_the_id():
    namespaced = MUTEX_PNML.replace(
        b"<pnml>", b'<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">'
    )
    assert net_id_of(document=import_pnml(payload=namespaced, limits=LIMITS)) == net_id_of(
        document=import_pnml(payload=MUTEX_PNML, limits=LIMITS)
    )


def test_element_order_and_white_space_do_not_change_the_id():
    lines = MUTEX_PNML.split(b"\n")
    arcs = [line for line in lines if line.startswith(b"  <arc")]
    others = [line for line in lines if not line.startswith(b"  <arc")]
    shuffled = b"\n".join(others[:-1] + arcs[::-1] + others[-1:])
    assert net_id_of(document=import_pnml(payload=shuffled, limits=LIMITS)) == net_id_of(
        document=import_pnml(payload=MUTEX_PNML, limits=LIMITS)
    )


def test_a_file_with_several_nets_is_refused():
    payload = b'<pnml><net id="a" type="t"/><net id="b" type="t"/></pnml>'
    with pytest.raises(PnmlError, match="several nets"):
        import_pnml(payload=payload, limits=LIMITS)


@pytest.mark.parametrize(
    "payload", [b"", b"<pnml/>", b"<other/>", b"<pnml><x/></pnml>", b"<a><b></a>"]
)
def test_non_pnml_is_refused(payload):
    with pytest.raises(PnmlError):
        import_pnml(payload=payload, limits=LIMITS)


def test_non_integer_pt_marking_is_refused_with_a_line():
    payload = b"""<pnml><net id="n" type="http://www.pnml.org/version-2009/grammar/ptnet">
<place id="p"><initialMarking><text>many</text></initialMarking></place></net></pnml>"""
    with pytest.raises(PnmlError) as caught:
        import_pnml(payload=payload, limits=LIMITS)
    assert caught.value.location == "line 2"


def test_dangling_arc_reports_the_line_of_the_arc():
    payload = b"""<pnml><net id="n" type="http://www.pnml.org/version-2009/grammar/ptnet">
<place id="p"/>
<transition id="t"/>
<arc id="a" source="p" target="zzz"/></net></pnml>"""
    with pytest.raises(PnmlError) as caught:
        import_pnml(payload=payload, limits=LIMITS)
    assert caught.value.location == "line 4"


def test_duplicate_ids_across_pages_are_refused():
    payload = b"""<pnml><net id="n" type="t"><page id="a"><place id="x"/></page>
<page id="b"><place id="x"/></page></net></pnml>"""
    with pytest.raises(PnmlError, match="duplicate"):
        import_pnml(payload=payload, limits=LIMITS)


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE pnml [<!ENTITY a "x">]>'
        b'<pnml><net id="n" type="t"><name>&a;</name></net></pnml>',
        b'<!DOCTYPE pnml SYSTEM "http://example.org/x.dtd"><pnml/>',
    ],
)
def test_dtds_and_entities_are_refused(payload):
    with pytest.raises(PnmlError, match="Refused"):
        import_pnml(payload=payload, limits=LIMITS)


def test_deep_nesting_is_refused():
    payload = b"<pnml>" + b"<a>" * 100 + b"</a>" * 100 + b"</pnml>"
    with pytest.raises(PnmlError, match="nested too deeply"):
        import_pnml(payload=payload, limits=LIMITS)


def test_huge_counts_are_refused():
    payload = b'<pnml><net id="n" type="t">' + b'<place id="p"/>' * 20 + b"</net></pnml>"
    with pytest.raises(PnmlError, match="too many XML elements"):
        import_pnml(payload=payload, limits=DocumentLimits(max_xml_elements=10))
    with pytest.raises(PnmlError, match="too many elements"):
        import_pnml(
            payload=payload.replace(b'id="p"', b'id="q"', 0), limits=DocumentLimits(max_elements=5)
        )


@pytest.mark.parametrize(
    "fragment",
    [
        b"<place/>",
        b'<transition id="t"/><arc id="a" source="t"/>',
        b'<place id="p"><graphics><weird/></graphics></place>',
        b'<place id="p"><graphics><position x="a" y="1"/></graphics></place>',
        b'<place id="p"><graphics><position x="1" y="1" z="2"/></graphics></place>',
        b'<place id="p"><graphics><fill foo="1"/></graphics></place>',
        b'<place id="p"><initialMarking/><hlinitialMarking/></place>',
        b'<transition id="t"/><place id="p"/><arc id="a" source="p" target="t">'
        b"<inscription/><hlinscription/></arc>",
        b'<place id="p"><toolspecific tool="x"/></place>',
        b'<place id="p"><graphics><position x="1" y="1"/>'
        b'<position x="2" y="2"/></graphics></place>',
    ],
)
def test_constructs_that_cannot_be_kept_are_refused(fragment):
    payload = b'<pnml><net id="n" type="t">' + fragment + b"</net></pnml>"
    with pytest.raises(PnmlError):
        import_pnml(payload=payload, limits=LIMITS)


def test_colored_declarations_terms_and_conditions_are_kept_as_xml_trees():
    payload = b"""<pnml><net id="c" type="http://www.pnml.org/version-2009/grammar/symmetricnet">
<declaration><structure><declarations>
<namedsort id="s" name="S"/></declarations></structure></declaration>
<place id="p"><type><text>S</text><structure><usersort declaration="s"/></structure></type>
<hlinitialMarking><text>1`all</text><structure><numberof/></structure></hlinitialMarking></place>
<transition id="t"><condition><text>true</text></condition></transition>
<arc id="a" source="p" target="t">
<hlinscription><text>x</text></hlinscription></arc></net></pnml>"""
    document = import_pnml(payload=payload, limits=LIMITS)
    assert document.kind == "symmetric"
    assert document.declaration is not None
    assert document.declaration.structure is not None
    assert document.places[0].place_type is not None
    assert document.places[0].place_type.structure is not None
    assert document.places[0].initial_marking is not None
    assert document.places[0].initial_marking.text == "1`all"
    assert document.transitions[0].condition is not None
    assert document.arcs[0].inscription is not None
    assert document.arcs[0].inscription.text == "x"
