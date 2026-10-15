"""The canonical net document: a JSON-friendly model of a Petri net (ADR 0015).

Everything PNML can say is kept: pages, reference nodes, graphics, tool-specific data, colored
declarations and terms (as generic XML trees) and unknown extensions. Only lexical details are
dropped. See docs/net-document.md for the shape and the mapping from PNML.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, computed_field, field_validator

from .models import DomainModel

NET_DOCUMENT_VERSION: Literal["1.0"] = "1.0"

PTNET_TYPE_URI = "http://www.pnml.org/version-2009/grammar/ptnet"

NetKind = Literal["pt", "symmetric", "hlpn", "core", "other"]

# Fragments of the PNML grammar URIs, from the most to the least specific.
KIND_BY_URI_FRAGMENT: tuple[tuple[str, NetKind], ...] = (
    ("symmetricnet", "symmetric"),
    ("highlevelnet", "hlpn"),
    ("hlpn", "hlpn"),
    ("ptnet", "pt"),
    ("pnmlcoremodel", "core"),
)


def sorted_attributes(*, attributes: tuple[XmlAttribute, ...]) -> tuple[XmlAttribute, ...]:
    """Return ``attributes`` ordered by name; refuse a name used twice."""
    names = [attribute.name for attribute in attributes]
    if len(set(names)) != len(names):
        message = "an attribute name is used twice"
        raise ValueError(message)
    return tuple(sorted(attributes, key=lambda attribute: attribute.name))


class XmlAttribute(DomainModel):
    """An attribute of a generic XML node; the name is qualified by its namespace URI if any."""

    name: str
    value: str


class XmlNode(DomainModel):
    """A generic XML element, kept losslessly (mixed content included)."""

    name: str
    attributes: tuple[XmlAttribute, ...] = ()
    content: tuple[XmlNode | str, ...] = ()

    @field_validator("attributes")
    @classmethod
    def _order_attributes(  # noqa: PLR0917 - pydantic calls validators positionally
        cls, attributes: tuple[XmlAttribute, ...]
    ) -> tuple[XmlAttribute, ...]:
        """Order attributes by name: their order in a file is lexical."""
        return sorted_attributes(attributes=attributes)


class ToolSpecific(DomainModel):
    """Opaque tool-specific data, kept in order."""

    tool: str
    version: str
    content: tuple[XmlNode | str, ...] = ()


class Extensible(DomainModel):
    """What every PNML object may carry besides its own fields."""

    tool_specific: tuple[ToolSpecific, ...] = ()
    extensions: tuple[XmlNode, ...] = ()
    extra_attributes: tuple[XmlAttribute, ...] = ()

    @field_validator("extra_attributes")
    @classmethod
    def _order_extra_attributes(  # noqa: PLR0917 - pydantic calls validators positionally
        cls, attributes: tuple[XmlAttribute, ...]
    ) -> tuple[XmlAttribute, ...]:
        """Order attributes by name: their order in a file is lexical."""
        return sorted_attributes(attributes=attributes)


class Coordinates(DomainModel):
    """A point or a dimension."""

    x: float
    y: float


class Fill(DomainModel):
    """Graphical fill; values are kept as written."""

    color: str | None = None
    gradient_color: str | None = None
    gradient_rotation: str | None = None
    image: str | None = None


class Line(DomainModel):
    """Graphical line; values are kept as written."""

    shape: str | None = None
    color: str | None = None
    width: str | None = None
    style: str | None = None


class Font(DomainModel):
    """Graphical font; values are kept as written."""

    family: str | None = None
    style: str | None = None
    weight: str | None = None
    size: str | None = None
    decoration: str | None = None
    align: str | None = None
    rotation: str | None = None


class NodeGraphics(DomainModel):
    """Graphics of a place, transition, reference node or page."""

    position: Coordinates | None = None
    dimension: Coordinates | None = None
    fill: Fill | None = None
    line: Line | None = None


class ArcGraphics(DomainModel):
    """Graphics of an arc: intermediate points and line."""

    positions: tuple[Coordinates, ...] = ()
    line: Line | None = None


class AnnotationGraphics(DomainModel):
    """Graphics of an annotation."""

    offset: Coordinates | None = None
    fill: Fill | None = None
    line: Line | None = None
    font: Font | None = None


class Annotation(Extensible):
    """A name, marking, inscription, type, guard or declaration.

    ``text`` is kept as written; typed values are derived from it, not stored twice.
    """

    text: str | None = None
    structure: XmlNode | None = None
    graphics: AnnotationGraphics | None = None


class Place(Extensible):
    """A place."""

    id: str = Field(min_length=1)
    name: Annotation | None = None
    initial_marking: Annotation | None = None
    place_type: Annotation | None = None
    graphics: NodeGraphics | None = None


class Transition(Extensible):
    """A transition."""

    id: str = Field(min_length=1)
    name: Annotation | None = None
    condition: Annotation | None = None
    graphics: NodeGraphics | None = None


class RefPlace(Extensible):
    """A reference to a place (or to another reference place) of another page."""

    id: str = Field(min_length=1)
    ref: str
    name: Annotation | None = None
    graphics: NodeGraphics | None = None


class RefTransition(Extensible):
    """A reference to a transition (or to another reference transition) of another page."""

    id: str = Field(min_length=1)
    ref: str
    name: Annotation | None = None
    graphics: NodeGraphics | None = None


class Arc(Extensible):
    """An arc between a place-like and a transition-like node, in either direction."""

    id: str = Field(min_length=1)
    source: str
    target: str
    name: Annotation | None = None
    inscription: Annotation | None = None
    graphics: ArcGraphics | None = None


class Container(Extensible):
    """What a net and a page have in common: elements, nested pages and annotations."""

    name: Annotation | None = None
    declaration: Annotation | None = None
    graphics: NodeGraphics | None = None
    pages: tuple[Page, ...] = ()
    places: tuple[Place, ...] = ()
    transitions: tuple[Transition, ...] = ()
    arcs: tuple[Arc, ...] = ()
    ref_places: tuple[RefPlace, ...] = ()
    ref_transitions: tuple[RefTransition, ...] = ()

    def located_containers(self) -> tuple[LocatedContainer, ...]:
        """Return this container and every nested page, parents first, with pointer and depth."""
        found: list[LocatedContainer] = []
        pending = [LocatedContainer(pointer="", depth=1, page_id=None, container=self)]
        while pending:
            current = pending.pop(0)
            found.append(current)
            pending.extend(
                LocatedContainer(
                    pointer=f"{current.pointer}/pages/{index}",
                    depth=current.depth + 1,
                    page_id=page.id,
                    container=page,
                )
                for index, page in enumerate(current.container.pages)
            )
        return tuple(found)

    def sorted_by_id(self) -> Self:
        """Return a copy whose children, at every depth, are ordered by id (canonical form)."""
        return self.model_copy(
            update={
                "pages": tuple(sorted((page.sorted_by_id() for page in self.pages), key=_id)),
                "places": tuple(sorted(self.places, key=_id)),
                "transitions": tuple(sorted(self.transitions, key=_id)),
                "arcs": tuple(sorted(self.arcs, key=_id)),
                "ref_places": tuple(sorted(self.ref_places, key=_id)),
                "ref_transitions": tuple(sorted(self.ref_transitions, key=_id)),
            }
        )


def _id(element: Page | Place | Transition | Arc | RefPlace | RefTransition) -> str:  # noqa: PLR0917 - sort key
    """Return the id of an element, to sort by it."""
    return element.id


class LocatedContainer(DomainModel):
    """A container with where it sits in the document: JSON pointer and page depth (net = 1)."""

    pointer: str
    depth: int
    page_id: str | None
    container: Container


class Page(Container):
    """A page: a container with an id."""

    id: str = Field(min_length=1)


class NetDocument(Container):
    """A Petri net. ``schema_version`` is not part of the identity (ADR 0015)."""

    schema_version: Literal["1.0"] = NET_DOCUMENT_VERSION
    source_id: str = Field(min_length=1)
    type_uri: str

    @computed_field  # type: ignore[prop-decorator]  # mypy does not model computed_field over property
    @property
    def kind(self) -> NetKind:
        """Return the family of the net, derived from its type URI."""
        lowered = self.type_uri.lower()
        for fragment, kind in KIND_BY_URI_FRAGMENT:
            if fragment in lowered:
                return kind
        return "other"
