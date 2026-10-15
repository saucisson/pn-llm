"""PNML exporter: deterministic PNML text rendered from a ``NetDocument`` (ADR 0015).

Same document, same bytes. Structural elements are written without a namespace; a name in a
namespace gets a prefix declared on the element itself (``ns0`` for the element, ``ns1``... for
its attributes, in sorted order of namespace). Children of every container are ordered by id.
Importing the output gives back the same document: that is the round-trip contract.
"""

from __future__ import annotations

import re

from .errors import InvalidNetError
from .models import DomainModel
from .net_document import (
    Annotation,
    AnnotationGraphics,
    Arc,
    ArcGraphics,
    Container,
    Coordinates,
    Fill,
    Font,
    Line,
    NetDocument,
    NodeGraphics,
    Page,
    Place,
    RefPlace,
    RefTransition,
    ToolSpecific,
    Transition,
    XmlAttribute,
    XmlNode,
)

INDENT = "  "
HIGH_LEVEL_KINDS = frozenset({"symmetric", "hlpn"})

# Characters XML 1.0 cannot carry, even as character references.
FORBIDDEN_XML_CHARACTERS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


class QualifiedName(DomainModel):
    """A name split into its namespace URI ("" if none) and local part."""

    namespace: str
    local: str


def split_name(*, name: str) -> QualifiedName:
    """Split ``{namespace}local`` into its two parts."""
    if name.startswith("{"):
        namespace, _, local = name[1:].partition("}")
        return QualifiedName(namespace=namespace, local=local)
    return QualifiedName(namespace="", local=name)


def escape_text(*, value: str) -> str:
    """Escape character data so that it parses back to the same string."""
    if FORBIDDEN_XML_CHARACTERS.search(value):
        message = "the net holds a character that XML cannot carry"
        raise InvalidNetError(message)
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")
    )


def escape_attribute(*, value: str) -> str:
    """Escape an attribute value; white space is written as references so it is not normalized."""
    return (
        escape_text(value=value).replace('"', "&quot;").replace("\n", "&#10;").replace("\t", "&#9;")
    )


def start_tag(
    *, name: str, attributes: tuple[XmlAttribute, ...], self_closing: bool = False
) -> str:
    """Return the start tag of an element, declaring the prefixes its names need."""
    qualified = split_name(name=name)
    namespaces = sorted({split_name(name=a.name).namespace for a in attributes} - {""})
    declarations: list[str] = []
    prefix_of = {namespace: f"ns{index + 1}" for index, namespace in enumerate(namespaces)}
    tag = qualified.local
    if qualified.namespace:
        tag = f"ns0:{qualified.local}"
        declarations.append(f'xmlns:ns0="{escape_attribute(value=qualified.namespace)}"')
    declarations.extend(
        f'xmlns:{prefix}="{escape_attribute(value=namespace)}"'
        for namespace, prefix in prefix_of.items()
    )
    rendered = []
    for attribute in attributes:
        attribute_name = split_name(name=attribute.name)
        written = (
            f"{prefix_of[attribute_name.namespace]}:{attribute_name.local}"
            if attribute_name.namespace
            else attribute_name.local
        )
        rendered.append(f'{written}="{escape_attribute(value=attribute.value)}"')
    parts = [tag, *declarations, *rendered]
    return "<" + " ".join(parts) + ("/>" if self_closing else ">")


def end_tag(*, name: str) -> str:
    """Return the end tag matching ``start_tag`` for ``name``."""
    qualified = split_name(name=name)
    return f"</ns0:{qualified.local}>" if qualified.namespace else f"</{qualified.local}>"


def render_xml_node(*, node: XmlNode | str) -> str:
    """Render a generic XML tree compactly: mixed content must not receive indentation."""
    if isinstance(node, str):
        return escape_text(value=node)
    if not node.content:
        return start_tag(name=node.name, attributes=node.attributes, self_closing=True)
    body = "".join(render_xml_node(node=child) for child in node.content)
    return start_tag(name=node.name, attributes=node.attributes) + body + end_tag(name=node.name)


def render_element(
    *, name: str, attributes: tuple[XmlAttribute, ...], children: tuple[str, ...], depth: int
) -> str:
    """Render a structural element whose children are complete lines, one per child."""
    pad = INDENT * depth
    if not children:
        return pad + start_tag(name=name, attributes=attributes, self_closing=True)
    inner = "\n".join(children)
    return f"{pad}{start_tag(name=name, attributes=attributes)}\n{inner}\n{pad}{end_tag(name=name)}"


def render_raw(*, node: XmlNode | str, depth: int) -> str:
    """Render an opaque XML tree on one line, indented as a child."""
    return INDENT * depth + render_xml_node(node=node)


def render_coordinates(*, name: str, value: Coordinates, depth: int) -> str:
    """Render a position, dimension or offset."""
    attributes = (
        XmlAttribute(name="x", value=number(value=value.x)),
        XmlAttribute(name="y", value=number(value=value.y)),
    )
    return render_element(name=name, attributes=attributes, children=(), depth=depth)


def number(*, value: float) -> str:
    """Write a coordinate without a useless fraction."""
    return str(int(value)) if value == int(value) else repr(value)


def render_style(*, name: str, style: Fill | Line | Font, depth: int) -> str:
    """Render a fill, line or font: its set fields become attributes, hyphenated as in PNML."""
    attributes = tuple(
        XmlAttribute(name=field.replace("_", "-"), value=value)
        for field, value in style
        if value is not None
    )
    return render_element(name=name, attributes=attributes, children=(), depth=depth)


def render_node_graphics(*, graphics: NodeGraphics, depth: int) -> str:
    """Render the ``graphics`` of a node or page."""
    children: list[str] = []
    if graphics.position is not None:
        children.append(
            render_coordinates(name="position", value=graphics.position, depth=depth + 1)
        )
    if graphics.dimension is not None:
        children.append(
            render_coordinates(name="dimension", value=graphics.dimension, depth=depth + 1)
        )
    if graphics.fill is not None:
        children.append(render_style(name="fill", style=graphics.fill, depth=depth + 1))
    if graphics.line is not None:
        children.append(render_style(name="line", style=graphics.line, depth=depth + 1))
    return render_element(name="graphics", attributes=(), children=tuple(children), depth=depth)


def render_arc_graphics(*, graphics: ArcGraphics, depth: int) -> str:
    """Render the ``graphics`` of an arc."""
    children = [
        render_coordinates(name="position", value=position, depth=depth + 1)
        for position in graphics.positions
    ]
    if graphics.line is not None:
        children.append(render_style(name="line", style=graphics.line, depth=depth + 1))
    return render_element(name="graphics", attributes=(), children=tuple(children), depth=depth)


def render_annotation_graphics(*, graphics: AnnotationGraphics, depth: int) -> str:
    """Render the ``graphics`` of an annotation."""
    children: list[str] = []
    if graphics.offset is not None:
        children.append(render_coordinates(name="offset", value=graphics.offset, depth=depth + 1))
    if graphics.fill is not None:
        children.append(render_style(name="fill", style=graphics.fill, depth=depth + 1))
    if graphics.line is not None:
        children.append(render_style(name="line", style=graphics.line, depth=depth + 1))
    if graphics.font is not None:
        children.append(render_style(name="font", style=graphics.font, depth=depth + 1))
    return render_element(name="graphics", attributes=(), children=tuple(children), depth=depth)


def render_tool_specific(*, tool_specific: ToolSpecific, depth: int) -> str:
    """Render one ``toolspecific`` element, its content compact and in order."""
    pad = INDENT * depth
    attributes = (
        XmlAttribute(name="tool", value=tool_specific.tool),
        XmlAttribute(name="version", value=tool_specific.version),
    )
    if not tool_specific.content:
        return pad + start_tag(name="toolspecific", attributes=attributes, self_closing=True)
    body = "".join(render_xml_node(node=item) for item in tool_specific.content)
    return (
        pad
        + start_tag(name="toolspecific", attributes=attributes)
        + body
        + end_tag(name="toolspecific")
    )


class ExtensibleParts(DomainModel):
    """The rendered tool-specific data and extensions of an object, to append to its children."""

    lines: tuple[str, ...]
    attributes: tuple[XmlAttribute, ...]


def extensible_parts(
    *,
    tool_specific: tuple[ToolSpecific, ...],
    extensions: tuple[XmlNode, ...],
    extra_attributes: tuple[XmlAttribute, ...],
    depth: int,
) -> ExtensibleParts:
    """Render what every object may carry besides its own fields."""
    lines = tuple(render_tool_specific(tool_specific=item, depth=depth) for item in tool_specific)
    lines += tuple(render_raw(node=item, depth=depth) for item in extensions)
    return ExtensibleParts(lines=lines, attributes=extra_attributes)


def render_annotation(*, name: str, annotation: Annotation | None, depth: int) -> tuple[str, ...]:
    """Render an optional annotation as zero or one line."""
    if annotation is None:
        return ()
    children: list[str] = []
    if annotation.text is not None:
        children.append(
            INDENT * (depth + 1)
            + start_tag(name="text", attributes=())
            + escape_text(value=annotation.text)
            + end_tag(name="text")
        )
    if annotation.structure is not None:
        children.append(render_raw(node=annotation.structure, depth=depth + 1))
    if annotation.graphics is not None:
        children.append(render_annotation_graphics(graphics=annotation.graphics, depth=depth + 1))
    parts = extensible_parts(
        tool_specific=annotation.tool_specific,
        extensions=annotation.extensions,
        extra_attributes=annotation.extra_attributes,
        depth=depth + 1,
    )
    return (
        render_element(
            name=name,
            attributes=parts.attributes,
            children=(*children, *parts.lines),
            depth=depth,
        ),
    )


def render_place(*, place: Place, high_level: bool, depth: int) -> str:
    """Render a ``place``."""
    children = (
        *render_annotation(name="name", annotation=place.name, depth=depth + 1),
        *render_annotation(
            name="hlinitialMarking" if high_level else "initialMarking",
            annotation=place.initial_marking,
            depth=depth + 1,
        ),
        *render_annotation(name="type", annotation=place.place_type, depth=depth + 1),
        *(
            ()
            if place.graphics is None
            else (render_node_graphics(graphics=place.graphics, depth=depth + 1),)
        ),
    )
    parts = extensible_parts(
        tool_specific=place.tool_specific,
        extensions=place.extensions,
        extra_attributes=place.extra_attributes,
        depth=depth + 1,
    )
    attributes = (XmlAttribute(name="id", value=place.id), *parts.attributes)
    return render_element(
        name="place", attributes=attributes, children=(*children, *parts.lines), depth=depth
    )


def render_transition(*, transition: Transition, depth: int) -> str:
    """Render a ``transition``."""
    children = (
        *render_annotation(name="name", annotation=transition.name, depth=depth + 1),
        *render_annotation(name="condition", annotation=transition.condition, depth=depth + 1),
        *(
            ()
            if transition.graphics is None
            else (render_node_graphics(graphics=transition.graphics, depth=depth + 1),)
        ),
    )
    parts = extensible_parts(
        tool_specific=transition.tool_specific,
        extensions=transition.extensions,
        extra_attributes=transition.extra_attributes,
        depth=depth + 1,
    )
    attributes = (XmlAttribute(name="id", value=transition.id), *parts.attributes)
    return render_element(
        name="transition", attributes=attributes, children=(*children, *parts.lines), depth=depth
    )


def render_reference(*, reference: RefPlace | RefTransition, depth: int) -> str:
    """Render a ``referencePlace`` or ``referenceTransition``."""
    children = (
        *render_annotation(name="name", annotation=reference.name, depth=depth + 1),
        *(
            ()
            if reference.graphics is None
            else (render_node_graphics(graphics=reference.graphics, depth=depth + 1),)
        ),
    )
    parts = extensible_parts(
        tool_specific=reference.tool_specific,
        extensions=reference.extensions,
        extra_attributes=reference.extra_attributes,
        depth=depth + 1,
    )
    attributes = (
        XmlAttribute(name="id", value=reference.id),
        XmlAttribute(name="ref", value=reference.ref),
        *parts.attributes,
    )
    name = "referencePlace" if isinstance(reference, RefPlace) else "referenceTransition"
    return render_element(
        name=name, attributes=attributes, children=(*children, *parts.lines), depth=depth
    )


def render_arc(*, arc: Arc, high_level: bool, depth: int) -> str:
    """Render an ``arc``."""
    children = (
        *render_annotation(name="name", annotation=arc.name, depth=depth + 1),
        *render_annotation(
            name="hlinscription" if high_level else "inscription",
            annotation=arc.inscription,
            depth=depth + 1,
        ),
        *(
            ()
            if arc.graphics is None
            else (render_arc_graphics(graphics=arc.graphics, depth=depth + 1),)
        ),
    )
    parts = extensible_parts(
        tool_specific=arc.tool_specific,
        extensions=arc.extensions,
        extra_attributes=arc.extra_attributes,
        depth=depth + 1,
    )
    attributes = (
        XmlAttribute(name="id", value=arc.id),
        XmlAttribute(name="source", value=arc.source),
        XmlAttribute(name="target", value=arc.target),
        *parts.attributes,
    )
    return render_element(
        name="arc", attributes=attributes, children=(*children, *parts.lines), depth=depth
    )


def render_container(
    *,
    name: str,
    container: Container,
    own_attributes: tuple[XmlAttribute, ...],
    high_level: bool,
    depth: int,
) -> str:
    """Render a ``net`` or a ``page`` with everything inside it."""
    children = (
        *render_annotation(name="name", annotation=container.name, depth=depth + 1),
        *render_annotation(name="declaration", annotation=container.declaration, depth=depth + 1),
        *(
            ()
            if container.graphics is None
            else (render_node_graphics(graphics=container.graphics, depth=depth + 1),)
        ),
        *(render_place(place=p, high_level=high_level, depth=depth + 1) for p in container.places),
        *(render_transition(transition=t, depth=depth + 1) for t in container.transitions),
        *(render_reference(reference=r, depth=depth + 1) for r in container.ref_places),
        *(render_reference(reference=r, depth=depth + 1) for r in container.ref_transitions),
        *(render_arc(arc=a, high_level=high_level, depth=depth + 1) for a in container.arcs),
        *(
            render_page(page=page, high_level=high_level, depth=depth + 1)
            for page in container.pages
        ),
    )
    parts = extensible_parts(
        tool_specific=container.tool_specific,
        extensions=container.extensions,
        extra_attributes=container.extra_attributes,
        depth=depth + 1,
    )
    return render_element(
        name=name,
        attributes=(*own_attributes, *parts.attributes),
        children=(*children, *parts.lines),
        depth=depth,
    )


def render_page(*, page: Page, high_level: bool, depth: int) -> str:
    """Render a ``page``."""
    return render_container(
        name="page",
        container=page,
        own_attributes=(XmlAttribute(name="id", value=page.id),),
        high_level=high_level,
        depth=depth,
    )


def render_pnml(*, document: NetDocument) -> bytes:
    """Render a document as PNML: UTF-8 bytes, identical for identical documents.

    Raises:
        InvalidNetError: if a string holds a character XML cannot carry.
    """
    ordered = document.sorted_by_id()
    net = render_container(
        name="net",
        container=ordered,
        own_attributes=(
            XmlAttribute(name="id", value=ordered.source_id),
            XmlAttribute(name="type", value=ordered.type_uri),
        ),
        high_level=ordered.kind in HIGH_LEVEL_KINDS,
        depth=1,
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<pnml>\n{net}\n</pnml>\n'.encode()
