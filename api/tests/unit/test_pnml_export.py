import pytest

from app.domain.canonical import net_id_of
from app.domain.errors import InvalidNetError
from app.domain.net_document import (
    PTNET_TYPE_URI,
    Annotation,
    NetDocument,
    Place,
    ToolSpecific,
    XmlAttribute,
    XmlNode,
)
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_export import render_pnml
from app.domain.pnml_import import import_pnml
from tests.support import MUTEX_PNML
from tests.unit.test_pnml_import import RICH

LIMITS = DocumentLimits()

COLORED = b"""<pnml><net id="c" type="http://www.pnml.org/version-2009/grammar/symmetricnet">
<declaration><structure><declarations>
<namedsort id="s" name="S"/></declarations></structure></declaration>
<place id="p"><type><text>S</text>
<structure><usersort declaration="s"/></structure></type>
<hlinitialMarking><text>1`all</text><structure><numberof/></structure></hlinitialMarking></place>
<transition id="t"><condition><text>true</text></condition></transition>
<arc id="a" source="p" target="t">
<hlinscription><text>x</text></hlinscription></arc></net></pnml>"""

FOREIGN = b"""<pnml><net id="f" type="t" xmlns:x="urn:x" x:flag="a &amp; b&#10;c">
<toolspecific tool="t" version="1">
<x:data x:k="v" plain="1">text &lt; more
<x:inner/> tail</x:data></toolspecific>
<place id="p">
<name><text> spaced &amp; &lt;odd&gt; </text></name></place>
<x:other y="1"/></net></pnml>"""


@pytest.mark.parametrize(
    "payload", [MUTEX_PNML, RICH, COLORED, FOREIGN], ids=["mutex", "rich", "colored", "foreign"]
)
def test_round_trip_is_a_fixed_point(payload):
    first = import_pnml(payload=payload, limits=LIMITS)
    rendered = render_pnml(document=first)
    second = import_pnml(payload=rendered, limits=LIMITS)
    assert second.sorted_by_id() == first.sorted_by_id()
    assert net_id_of(document=second) == net_id_of(document=first)
    assert render_pnml(document=second) == rendered


def test_same_document_gives_the_same_bytes_whatever_the_input_order():
    lines = MUTEX_PNML.split(b"\n")
    arcs = [line for line in lines if line.startswith(b"  <arc")]
    others = [line for line in lines if not line.startswith(b"  <arc")]
    shuffled = b"\n".join(others[:-1] + arcs[::-1] + others[-1:])
    assert render_pnml(document=import_pnml(payload=shuffled, limits=LIMITS)) == render_pnml(
        document=import_pnml(payload=MUTEX_PNML, limits=LIMITS)
    )


def test_output_is_utf8_pnml_with_names_untouched():
    rendered = render_pnml(document=import_pnml(payload=MUTEX_PNML, limits=LIMITS)).decode()
    assert rendered.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<pnml>\n')
    assert '<place id="crit1">' in rendered
    assert "<text>idle1</text>" in rendered


def test_high_level_nets_use_high_level_element_names():
    rendered = render_pnml(document=import_pnml(payload=COLORED, limits=LIMITS)).decode()
    assert "<hlinitialMarking>" in rendered
    assert "<hlinscription>" in rendered
    assert "<initialMarking>" not in rendered


def test_white_space_and_special_characters_survive():
    document = import_pnml(payload=FOREIGN, limits=LIMITS)
    again = import_pnml(payload=render_pnml(document=document), limits=LIMITS)
    assert again.places[0].name is not None
    assert again.places[0].name.text == " spaced & <odd> "
    assert again.extra_attributes[0].value == "a & b\nc"


def test_unicode_names_are_not_normalized():
    name = "café → é"
    document = NetDocument(
        source_id="u", type_uri=PTNET_TYPE_URI, places=(Place(id="p", name=Annotation(text=name)),)
    )
    again = import_pnml(payload=render_pnml(document=document), limits=LIMITS)
    assert again.places[0].name is not None
    assert again.places[0].name.text == name


def test_characters_xml_cannot_carry_are_refused():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p", name=Annotation(text="bad\x00")),),
    )
    with pytest.raises(InvalidNetError):
        render_pnml(document=document)


def test_tool_specific_without_content_and_empty_nodes():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        tool_specific=(ToolSpecific(tool="a", version="1"),),
        extensions=(XmlNode(name="x", attributes=(XmlAttribute(name="k", value="v"),)),),
    )
    again = import_pnml(payload=render_pnml(document=document), limits=LIMITS)
    assert again.sorted_by_id() == document
