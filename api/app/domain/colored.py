"""Colored nets, typed: the sorts and variables declared in a symmetric net (docs/net-document.md).

The net document keeps declarations as generic XML trees so that nothing is lost. This module reads
them into typed models for summaries and estimates. It supports what the contest's symmetric nets
use (enumerations, integer ranges, products, dot); anything else is refused by name rather than
summarized wrongly.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field

from .errors import InvalidRequestError
from .models import DomainModel
from .net_document import NetDocument, Place, XmlNode


class UnsupportedColoredError(InvalidRequestError):
    """A construct of a colored net that this vocabulary does not cover."""


class SortConstant(DomainModel):
    """A value of an enumeration."""

    id: str
    name: str


class EnumerationSort(DomainModel):
    """A finite list of named values, cyclic when the successor of the last is the first."""

    kind: Literal["enumeration"] = "enumeration"
    id: str
    name: str
    constants: tuple[SortConstant, ...]
    cyclic: bool


class IntegerRangeSort(DomainModel):
    """The integers from ``start`` to ``end``, both included."""

    kind: Literal["range"] = "range"
    id: str
    name: str
    start: int
    end: int


class ProductSort(DomainModel):
    """Tuples of values of other sorts, named by their ids."""

    kind: Literal["product"] = "product"
    id: str
    name: str
    components: tuple[str, ...]


class DotSort(DomainModel):
    """The sort with a single value, used by places that only count tokens."""

    kind: Literal["dot"] = "dot"
    id: str = "dot"
    name: str = "dot"


class AliasSort(DomainModel):
    """A name for another sort."""

    kind: Literal["alias"] = "alias"
    id: str
    name: str
    target: str


Sort = Annotated[
    EnumerationSort | IntegerRangeSort | ProductSort | DotSort | AliasSort,
    Field(discriminator="kind"),
]


class Variable(DomainModel):
    """A variable of arc inscriptions and guards, with its sort."""

    id: str
    name: str
    sort: str


class Declarations(DomainModel):
    """What a colored net declares."""

    sorts: tuple[Sort, ...]
    variables: tuple[Variable, ...]

    def sort(self, *, sort_id: str) -> Sort:
        """Return a sort by id, or the dot sort for ``dot``.

        Raises:
            UnsupportedColoredError: if the net refers to a sort it does not declare.
        """
        if sort_id == "dot":
            return DotSort()
        found = next((s for s in self.sorts if s.id == sort_id), None)
        if found is None:
            raise UnsupportedColoredError(
                f"The net uses the sort {sort_id!r}, which it does not declare"
            )
        return found


def place_sort_id(*, place: Place) -> str:
    """Return the id of the sort a place of a colored net holds (``dot`` for the dot sort).

    Raises:
        UnsupportedColoredError: if the place declares no sort.
    """
    node = None if place.place_type is None else place.place_type.structure
    inner = () if node is None else children(node=node)
    if not inner:
        raise UnsupportedColoredError(f"The place {place.id!r} has no declared sort")
    if inner[0].name.endswith("}dot") or inner[0].name == "dot":
        return "dot"
    return next((a.value for a in inner[0].attributes if a.name == "declaration"), "")


def local(*, name: str) -> str:
    """Strip the namespace from a qualified XML name."""
    return name.rsplit("}", 1)[-1]


def children(*, node: XmlNode) -> tuple[XmlNode, ...]:
    """Return the element children of a node (text is not a child)."""
    return tuple(item for item in node.content if isinstance(item, XmlNode))


def attribute(*, node: XmlNode, name: str) -> str:
    """Return an attribute of a node, or refuse the net if it lacks it."""
    for item in node.attributes:
        if item.name == name:
            return item.value
    raise UnsupportedColoredError(f"<{local(name=node.name)}> without its {name!r} attribute")


def read_sort(*, node: XmlNode) -> Sort:
    """Read a ``namedsort`` declaration."""
    sort_id = attribute(node=node, name="id")
    name = attribute(node=node, name="name")
    body = children(node=node)
    if len(body) != 1:
        raise UnsupportedColoredError(f"The sort {name!r} has no single definition")
    definition = body[0]
    kind = local(name=definition.name)
    if kind in {"cyclicenumeration", "finiteenumeration"}:
        return EnumerationSort(
            id=sort_id,
            name=name,
            cyclic=kind == "cyclicenumeration",
            constants=tuple(
                SortConstant(id=attribute(node=c, name="id"), name=attribute(node=c, name="name"))
                for c in children(node=definition)
            ),
        )
    if kind == "finiteintrange":
        return IntegerRangeSort(
            id=sort_id,
            name=name,
            start=int(attribute(node=definition, name="start")),
            end=int(attribute(node=definition, name="end")),
        )
    if kind == "productsort":
        return ProductSort(
            id=sort_id,
            name=name,
            components=tuple(
                attribute(node=c, name="declaration") for c in children(node=definition)
            ),
        )
    if kind == "dot":
        return DotSort(id=sort_id, name=name)
    if kind == "usersort":
        return AliasSort(
            id=sort_id, name=name, target=attribute(node=definition, name="declaration")
        )
    raise UnsupportedColoredError(
        f"The sort {name!r} is defined with <{kind}>, which is not supported"
    )


def read_declarations(*, document: NetDocument) -> Declarations:
    """Read the sorts and variables a colored net declares.

    Raises:
        UnsupportedColoredError: if the net declares anything else (operators, partitions, ...)
            or defines a sort in a way that is not supported.
    """
    root = document.declaration.structure if document.declaration is not None else None
    if root is None:
        return Declarations(sorts=(), variables=())
    sorts: list[Sort] = []
    variables: list[Variable] = []
    for wrapper in children(node=root):
        if local(name=wrapper.name) != "declarations":
            raise UnsupportedColoredError(
                f"Unexpected <{local(name=wrapper.name)}> among the declarations"
            )
        for item in children(node=wrapper):
            kind = local(name=item.name)
            if kind == "namedsort":
                sorts.append(read_sort(node=item))
            elif kind == "variabledecl":
                (sort_node,) = children(node=item)
                variables.append(
                    Variable(
                        id=attribute(node=item, name="id"),
                        name=attribute(node=item, name="name"),
                        sort=attribute(node=sort_node, name="declaration"),
                    )
                )
            else:
                raise UnsupportedColoredError(f"The declaration <{kind}> is not supported")
    return Declarations(sorts=tuple(sorts), variables=tuple(variables))


def sort_size(*, declarations: Declarations, sort_id: str, depth: int = 0) -> int:
    """Return the number of values of a sort.

    Raises:
        UnsupportedColoredError: if sorts refer to each other in a loop.
    """
    if depth > len(declarations.sorts) + 1:
        raise UnsupportedColoredError("The sorts refer to each other in a loop")
    sort = declarations.sort(sort_id=sort_id)
    if isinstance(sort, EnumerationSort):
        return len(sort.constants)
    if isinstance(sort, IntegerRangeSort):
        return max(sort.end - sort.start + 1, 0)
    if isinstance(sort, ProductSort):
        return math.prod(
            sort_size(declarations=declarations, sort_id=c, depth=depth + 1)
            for c in sort.components
        )
    if isinstance(sort, AliasSort):
        return sort_size(declarations=declarations, sort_id=sort.target, depth=depth + 1)
    return 1
