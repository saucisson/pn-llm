"""PNML importer: hardened parsing and lossless conversion to a ``NetDocument`` (ADR 0015).

Everything PNML can say is kept: pages, reference nodes, graphics, tool-specific data, colored
declarations and terms (as generic XML trees), and any unknown element or attribute. Only lexical
details are dropped (comments, white space between elements, attribute order, namespace prefixes).
A construct that cannot be kept faithfully is refused, never silently lost.
"""

from __future__ import annotations

from xml.etree.ElementTree import ParseError  # exception type only: parsing uses defusedxml

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET  # hardened against DTDs and entity expansion
from pydantic import BaseModel, Field

from .errors import InvalidNetError, PnmlError
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
from .net_validation import DocumentLimits, validate_document

PNML_NAMESPACE_PREFIX = "http://www.pnml.org/"
CONTAINER_CHILDREN = frozenset(
    {"place", "transition", "arc", "referencePlace", "referenceTransition", "page"}
)


class PnmlElement(DomainModel):
    """An XML element as read from a file, with its line for error messages."""

    name: str  # "{namespace}local", or "local" without a namespace
    attributes: tuple[XmlAttribute, ...]
    children: tuple[PnmlElement | str, ...]
    line: int

    @property
    def local_name(self) -> str:
        """Return the element name without its namespace, or "" for a foreign namespace."""
        namespace, _, local = self.name.rpartition("}")
        if namespace and not namespace.removeprefix("{").startswith(PNML_NAMESPACE_PREFIX):
            return ""
        return local

    def elements(self) -> tuple[PnmlElement, ...]:
        """Return the child elements, without the text between them."""
        return tuple(child for child in self.children if isinstance(child, PnmlElement))

    def child(self, *, name: str) -> PnmlElement | None:
        """Return the first PNML child element called ``name``, if any."""
        return next((child for child in self.elements() if child.local_name == name), None)

    def attribute(self, *, name: str) -> str | None:
        """Return the value of an attribute, if present."""
        return next((attr.value for attr in self.attributes if attr.name == name), None)

    def text(self) -> str:
        """Return the text directly inside this element, as written."""
        return "".join(child for child in self.children if isinstance(child, str))

    def to_xml_node(self) -> XmlNode:
        """Convert this element and everything below it to a generic ``XmlNode``."""
        return XmlNode(
            name=self.name,
            attributes=self.attributes,
            content=tuple(
                child.to_xml_node() if isinstance(child, PnmlElement) else child
                for child in self.children
            ),
        )


class OpenElement(BaseModel):
    """An element being read: a mutable accumulator, private to the tree builder."""

    name: str
    attributes: tuple[XmlAttribute, ...]
    line: int
    children: list[PnmlElement | str] = Field(default_factory=list)


class PnmlTreeBuilder:
    """Parser target that builds ``PnmlElement`` trees, enforcing the size bounds as it goes."""

    def __init__(self, *, limits: DocumentLimits) -> None:
        """Create a builder bounded by ``limits``; ``bind`` must be called with the parser."""
        self._limits = limits
        self._parser: SafeET.XMLParser | None = None
        self._open: list[OpenElement] = []
        self._root: PnmlElement | None = None
        self._count = 0

    def bind(self, *, parser: SafeET.XMLParser) -> None:
        """Give the builder the parser, to read the current line."""
        self._parser = parser

    def line(self) -> int:
        """Return the line the parser is on (1 before the parser is bound)."""
        return 1 if self._parser is None else int(self._parser.parser.CurrentLineNumber)

    def start(self, tag: str, attrib: dict[str, str]) -> None:  # noqa: PLR0917 - parser target
        """Open an element."""
        self._count += 1
        if self._count > self._limits.max_xml_elements:
            raise PnmlError("too many XML elements", location=f"line {self.line()}")
        if len(self._open) >= self._limits.max_xml_depth:
            raise PnmlError("XML elements are nested too deeply", location=f"line {self.line()}")
        attributes = tuple(
            sorted(
                (XmlAttribute(name=name, value=value) for name, value in attrib.items()),
                key=lambda attribute: attribute.name,
            )
        )
        self._open.append(OpenElement(name=tag, attributes=attributes, line=self.line()))

    def data(self, data: str) -> None:  # noqa: PLR0917 - parser target
        """Add text to the open element."""
        self._open[-1].children.append(data)

    def end(self, tag: str) -> None:  # noqa: PLR0917 - parser target
        """Close the open element and attach it to its parent."""
        done = self._open.pop()
        # Merge adjacent text chunks, and drop white space that only separates child elements.
        merged: list[PnmlElement | str] = []
        for child in done.children:
            if isinstance(child, str) and merged and isinstance(merged[-1], str):
                merged[-1] = merged[-1] + child
            else:
                merged.append(child)
        has_elements = any(isinstance(child, PnmlElement) for child in merged)
        kept = tuple(
            child
            for child in merged
            if not (has_elements and isinstance(child, str) and not child.strip())
        )
        for child in kept:
            if isinstance(child, str) and len(child) > self._limits.max_string_length * 16:
                raise PnmlError("text too long", location=f"line {done.line}")
        element = PnmlElement(
            name=done.name, attributes=done.attributes, children=kept, line=done.line
        )
        if self._open:
            self._open[-1].children.append(element)
        else:
            self._root = element

    def close(self) -> PnmlElement | None:
        """Return the root element once the document is complete."""
        return self._root


def parse_xml(*, payload: bytes, limits: DocumentLimits) -> PnmlElement:
    """Parse XML with DTDs and entities refused and return the root element.

    Raises:
        PnmlError: if the XML is invalid, hostile or beyond the bounds.
    """
    builder = PnmlTreeBuilder(limits=limits)
    parser = SafeET.XMLParser(target=builder, forbid_dtd=True)
    builder.bind(parser=parser)
    try:
        parser.feed(payload)
        parser.close()
    except ParseError as exc:
        line = exc.position[0] if exc.position else 1
        raise PnmlError(f"Invalid XML: {exc}", location=f"line {line}") from exc
    except DefusedXmlException as exc:
        raise PnmlError(f"Refused XML construct: {exc}") from exc
    root = builder.close()
    if root is None:
        raise PnmlError("Empty document")
    return root


class ExtensibleFields(DomainModel):
    """The tool-specific data, unknown children and unknown attributes of one element."""

    tool_specific: tuple[ToolSpecific, ...]
    extensions: tuple[XmlNode, ...]
    extra_attributes: tuple[XmlAttribute, ...]


def extensible_fields(
    *, element: PnmlElement, known_children: frozenset[str], known_attributes: frozenset[str]
) -> ExtensibleFields:
    """Split off what an object does not model itself, so that nothing is lost.

    A known child is modelled once, except the repeatable ones (nodes, arcs, pages): a second
    child of the same name is kept as an extension.
    """
    tool_specific: list[ToolSpecific] = []
    extensions: list[XmlNode] = []
    seen: set[str] = set()
    for child in element.elements():
        local = child.local_name
        if local == "toolspecific":
            tool = child.attribute(name="tool")
            version = child.attribute(name="version")
            if tool is None or version is None:
                message = "toolspecific needs tool and version"
                raise PnmlError(message, location=f"line {child.line}")
            tool_specific.append(
                ToolSpecific(
                    tool=tool,
                    version=version,
                    content=tuple(
                        item.to_xml_node() if isinstance(item, PnmlElement) else item
                        for item in child.children
                    ),
                )
            )
        elif local in known_children and (local in CONTAINER_CHILDREN or local not in seen):
            seen.add(local)
        else:
            extensions.append(child.to_xml_node())
    extras = tuple(attr for attr in element.attributes if attr.name not in known_attributes)
    return ExtensibleFields(
        tool_specific=tuple(tool_specific), extensions=tuple(extensions), extra_attributes=extras
    )


def refuse_unknown_attributes(*, element: PnmlElement, known: frozenset[str]) -> None:
    """Raise if ``element`` has an attribute the document model cannot keep."""
    for attribute in element.attributes:
        if attribute.name not in known:
            message = f"unsupported attribute {attribute.name!r}"
            raise PnmlError(message, location=f"line {element.line}")


def read_coordinates(*, element: PnmlElement) -> Coordinates:
    """Read a ``position``, ``dimension`` or ``offset`` element."""
    refuse_unknown_attributes(element=element, known=frozenset({"x", "y"}))
    try:
        return Coordinates(
            x=float(element.attribute(name="x") or ""), y=float(element.attribute(name="y") or "")
        )
    except ValueError as exc:
        raise PnmlError("x and y must be numbers", location=f"line {element.line}") from exc


def read_fill(*, element: PnmlElement) -> Fill:
    """Read a ``fill`` element."""
    refuse_unknown_attributes(
        element=element, known=frozenset({"color", "gradient-color", "gradient-rotation", "image"})
    )
    return Fill(
        color=element.attribute(name="color"),
        gradient_color=element.attribute(name="gradient-color"),
        gradient_rotation=element.attribute(name="gradient-rotation"),
        image=element.attribute(name="image"),
    )


def read_line(*, element: PnmlElement) -> Line:
    """Read a ``line`` element."""
    refuse_unknown_attributes(
        element=element, known=frozenset({"shape", "color", "width", "style"})
    )
    return Line(
        shape=element.attribute(name="shape"),
        color=element.attribute(name="color"),
        width=element.attribute(name="width"),
        style=element.attribute(name="style"),
    )


def read_font(*, element: PnmlElement) -> Font:
    """Read a ``font`` element."""
    names = ("family", "style", "weight", "size", "decoration", "align", "rotation")
    refuse_unknown_attributes(element=element, known=frozenset(names))
    return Font(
        family=element.attribute(name="family"),
        style=element.attribute(name="style"),
        weight=element.attribute(name="weight"),
        size=element.attribute(name="size"),
        decoration=element.attribute(name="decoration"),
        align=element.attribute(name="align"),
        rotation=element.attribute(name="rotation"),
    )


def unsupported_graphics(*, child: PnmlElement) -> PnmlError:
    """Build the error for a graphics child that is unknown or repeated."""
    return PnmlError(f"unsupported graphics element {child.name!r}", location=f"line {child.line}")


def read_node_graphics(*, element: PnmlElement) -> NodeGraphics:
    """Read the ``graphics`` of a node or page."""
    refuse_unknown_attributes(element=element, known=frozenset())
    position = dimension = fill = line = None
    for child in element.elements():
        match child.local_name:
            case "position" if position is None:
                position = read_coordinates(element=child)
            case "dimension" if dimension is None:
                dimension = read_coordinates(element=child)
            case "fill" if fill is None:
                fill = read_fill(element=child)
            case "line" if line is None:
                line = read_line(element=child)
            case _:
                raise unsupported_graphics(child=child)
    return NodeGraphics(position=position, dimension=dimension, fill=fill, line=line)


def read_arc_graphics(*, element: PnmlElement) -> ArcGraphics:
    """Read the ``graphics`` of an arc."""
    refuse_unknown_attributes(element=element, known=frozenset())
    positions: list[Coordinates] = []
    line = None
    for child in element.elements():
        match child.local_name:
            case "position":
                positions.append(read_coordinates(element=child))
            case "line" if line is None:
                line = read_line(element=child)
            case _:
                raise unsupported_graphics(child=child)
    return ArcGraphics(positions=tuple(positions), line=line)


def read_annotation_graphics(*, element: PnmlElement) -> AnnotationGraphics:
    """Read the ``graphics`` of an annotation."""
    refuse_unknown_attributes(element=element, known=frozenset())
    offset = fill = line = font = None
    for child in element.elements():
        match child.local_name:
            case "offset" if offset is None:
                offset = read_coordinates(element=child)
            case "fill" if fill is None:
                fill = read_fill(element=child)
            case "line" if line is None:
                line = read_line(element=child)
            case "font" if font is None:
                font = read_font(element=child)
            case _:
                raise unsupported_graphics(child=child)
    return AnnotationGraphics(offset=offset, fill=fill, line=line, font=font)


def read_annotation(*, element: PnmlElement | None) -> Annotation | None:
    """Read a name, marking, inscription, type, condition or declaration, if present."""
    if element is None:
        return None
    text = element.child(name="text")
    structure = element.child(name="structure")
    graphics = element.child(name="graphics")
    fields = extensible_fields(
        element=element,
        known_children=frozenset({"text", "structure", "graphics"}),
        known_attributes=frozenset(),
    )
    return Annotation(
        text=None if text is None else text.text(),
        structure=None if structure is None else structure.to_xml_node(),
        graphics=None if graphics is None else read_annotation_graphics(element=graphics),
        tool_specific=fields.tool_specific,
        extensions=fields.extensions,
        extra_attributes=fields.extra_attributes,
    )


def required_attribute(*, element: PnmlElement, name: str) -> str:
    """Return a mandatory attribute or raise with the element's line."""
    value = element.attribute(name=name)
    if value is None:
        message = f"<{element.local_name}> needs the attribute {name!r}"
        raise PnmlError(message, location=f"line {element.line}")
    return value


def read_node_graphics_of(*, element: PnmlElement) -> NodeGraphics | None:
    """Read the optional ``graphics`` child of a node."""
    graphics = element.child(name="graphics")
    return None if graphics is None else read_node_graphics(element=graphics)


def read_place(*, element: PnmlElement) -> Place:
    """Read a ``place``."""
    marking = element.child(name="initialMarking")
    high_level = element.child(name="hlinitialMarking")
    if marking is not None and high_level is not None:
        message = "a place has both initialMarking and hlinitialMarking"
        raise PnmlError(message, location=f"line {element.line}")
    fields = extensible_fields(
        element=element,
        known_children=frozenset(
            {"name", "initialMarking", "hlinitialMarking", "type", "graphics"}
        ),
        known_attributes=frozenset({"id"}),
    )
    return Place(
        id=required_attribute(element=element, name="id"),
        name=read_annotation(element=element.child(name="name")),
        initial_marking=read_annotation(element=marking or high_level),
        place_type=read_annotation(element=element.child(name="type")),
        graphics=read_node_graphics_of(element=element),
        tool_specific=fields.tool_specific,
        extensions=fields.extensions,
        extra_attributes=fields.extra_attributes,
    )


def read_transition(*, element: PnmlElement) -> Transition:
    """Read a ``transition``."""
    fields = extensible_fields(
        element=element,
        known_children=frozenset({"name", "condition", "graphics"}),
        known_attributes=frozenset({"id"}),
    )
    return Transition(
        id=required_attribute(element=element, name="id"),
        name=read_annotation(element=element.child(name="name")),
        condition=read_annotation(element=element.child(name="condition")),
        graphics=read_node_graphics_of(element=element),
        tool_specific=fields.tool_specific,
        extensions=fields.extensions,
        extra_attributes=fields.extra_attributes,
    )


def read_reference(*, element: PnmlElement) -> RefPlace | RefTransition:
    """Read a ``referencePlace`` or a ``referenceTransition``."""
    fields = extensible_fields(
        element=element,
        known_children=frozenset({"name", "graphics"}),
        known_attributes=frozenset({"id", "ref"}),
    )
    reference_type = RefPlace if element.local_name == "referencePlace" else RefTransition
    return reference_type(
        id=required_attribute(element=element, name="id"),
        ref=required_attribute(element=element, name="ref"),
        name=read_annotation(element=element.child(name="name")),
        graphics=read_node_graphics_of(element=element),
        tool_specific=fields.tool_specific,
        extensions=fields.extensions,
        extra_attributes=fields.extra_attributes,
    )


def read_arc(*, element: PnmlElement) -> Arc:
    """Read an ``arc``."""
    inscription = element.child(name="inscription")
    high_level = element.child(name="hlinscription")
    if inscription is not None and high_level is not None:
        message = "an arc has both inscription and hlinscription"
        raise PnmlError(message, location=f"line {element.line}")
    graphics = element.child(name="graphics")
    fields = extensible_fields(
        element=element,
        known_children=frozenset({"name", "inscription", "hlinscription", "graphics"}),
        known_attributes=frozenset({"id", "source", "target"}),
    )
    return Arc(
        id=required_attribute(element=element, name="id"),
        source=required_attribute(element=element, name="source"),
        target=required_attribute(element=element, name="target"),
        name=read_annotation(element=element.child(name="name")),
        inscription=read_annotation(element=inscription or high_level),
        graphics=None if graphics is None else read_arc_graphics(element=graphics),
        tool_specific=fields.tool_specific,
        extensions=fields.extensions,
        extra_attributes=fields.extra_attributes,
    )


def read_container(*, element: PnmlElement, known_attributes: frozenset[str]) -> Container:
    """Read what a ``net`` and a ``page`` have in common: elements, pages and annotations."""
    fields = extensible_fields(
        element=element,
        known_children=frozenset({"name", "declaration", "graphics"}) | CONTAINER_CHILDREN,
        known_attributes=known_attributes,
    )
    # Elements keep their order in the file: error locations and the canonical sort rely on it.
    pages = tuple(
        read_page(element=child) for child in element.elements() if child.local_name == "page"
    )
    places = tuple(read_place(element=c) for c in element.elements() if c.local_name == "place")
    transitions = tuple(
        read_transition(element=c) for c in element.elements() if c.local_name == "transition"
    )
    arcs = tuple(read_arc(element=c) for c in element.elements() if c.local_name == "arc")
    ref_places = tuple(
        read_reference(element=c) for c in element.elements() if c.local_name == "referencePlace"
    )
    ref_transitions = tuple(
        read_reference(element=c)
        for c in element.elements()
        if c.local_name == "referenceTransition"
    )
    return Container(
        name=read_annotation(element=element.child(name="name")),
        declaration=read_annotation(element=element.child(name="declaration")),
        graphics=read_node_graphics_of(element=element),
        pages=pages,
        places=places,
        transitions=transitions,
        arcs=arcs,
        ref_places=ref_places,
        ref_transitions=ref_transitions,
        tool_specific=fields.tool_specific,
        extensions=fields.extensions,
        extra_attributes=fields.extra_attributes,
    )


def read_page(*, element: PnmlElement) -> Page:
    """Read a ``page`` with its nested pages."""
    container = read_container(element=element, known_attributes=frozenset({"id"}))
    return Page(id=required_attribute(element=element, name="id"), **dict(container))


def line_of_pointer(*, net: PnmlElement, pointer: str) -> int:
    """Return the line of the element a document JSON pointer designates."""
    names = {
        "pages": "page",
        "places": "place",
        "transitions": "transition",
        "arcs": "arc",
        "ref_places": "referencePlace",
        "ref_transitions": "referenceTransition",
    }
    current = net
    segments = [segment for segment in pointer.split("/") if segment]
    for group, index in zip(segments[::2], segments[1::2], strict=False):
        if group not in names or not index.isdigit():
            break
        matching = [c for c in current.elements() if c.local_name == names[group]]
        if int(index) >= len(matching):
            break
        current = matching[int(index)]
    return current.line


def import_pnml(*, payload: bytes, limits: DocumentLimits) -> NetDocument:
    """Convert a PNML file to a validated ``NetDocument``.

    Raises:
        PnmlError: if the file is not valid PNML, holds more than one net, or breaks a bound or a
            structural rule; ``location`` is a line number.
    """
    root = parse_xml(payload=payload, limits=limits)
    if root.local_name != "pnml":
        raise PnmlError("The root element must be <pnml>", location=f"line {root.line}")
    for child in root.elements():
        if child.local_name != "net":
            raise PnmlError(f"unexpected element {child.name!r}", location=f"line {child.line}")
    nets = root.elements()
    if len(nets) != 1:
        raise PnmlError(
            "A PNML file must hold exactly one net"
            if not nets
            else "A file with several nets is refused",
            location=f"line {root.line}",
        )
    net = nets[0]
    container = read_container(element=net, known_attributes=frozenset({"id", "type"}))
    document = NetDocument(
        source_id=required_attribute(element=net, name="id"),
        type_uri=required_attribute(element=net, name="type"),
        **dict(container),
    )
    try:
        validate_document(document=document, limits=limits)
    except InvalidNetError as exc:
        location = (
            None
            if exc.location is None
            else f"line {line_of_pointer(net=net, pointer=exc.location)}"
        )
        raise PnmlError(exc.reason, location=location) from exc
    return document
