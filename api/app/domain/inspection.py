"""Inspection results and computations: how the LLM and clients learn about a net (ADR 0013).

Everything here is derived from a ``NetStructure``. Names and ids are reported as they are in the
net; lists are sorted by id; anything cut short says so.
"""

from __future__ import annotations

import difflib
import re
from typing import Literal

from pydantic import Field

from .contract import ElementRef
from .errors import NotFoundError
from .models import DomainModel
from .net_structure import NetStructure, StructureNode
from .nets import NetSummary

# Largest numbers of places plus transitions for each size category.
SMALL_NET_MAX = 100
MEDIUM_NET_MAX = 10_000
LARGE_NET_MAX = 1_000_000

DETAIL_LINK_LIMIT = 100
SUGGESTION_SCAN_LIMIT = 20_000
MAX_NEIGHBOURHOOD_DEPTH = 5
DEFAULT_NEIGHBOURHOOD_NODES = 100
MAX_NEIGHBOURHOOD_NODES = 500

DIGITS = re.compile(r"\d+")


class NetOverview(DomainModel):
    """Counts and structural flags of a net: no names."""

    summary: NetSummary
    size_category: Literal["small", "medium", "large", "huge"]
    has_weighted_arcs: bool | None = Field(
        description="Some arc has a weight above 1; undefined for nets that are not P/T"
    )
    has_reference_nodes: bool


class ArcView(DomainModel):
    """An arc with both ends cited by reference."""

    id: str
    source: ElementRef
    target: ElementRef
    weight: int | None = None


class WeightedRef(DomainModel):
    """A neighbour of an element, and the arc that links them."""

    arc_id: str
    element: ElementRef
    weight: int | None = None


class Neighbours(DomainModel):
    """Some neighbours of an element: at most ``DETAIL_LINK_LIMIT``, with the real total."""

    items: tuple[WeightedRef, ...]
    total: int


class ElementDetail(DomainModel):
    """One place or transition with the elements around it.

    For a place, ``inputs`` are the transitions that put tokens in it and ``outputs`` those that
    take tokens out; for a transition, ``inputs`` are its source places and ``outputs`` its target
    places.
    """

    element: ElementRef
    tokens: int | None = None
    inputs: Neighbours
    outputs: Neighbours


class DistantElement(DomainModel):
    """An element of a neighbourhood and its distance, in arcs, from the nearest center."""

    element: ElementRef
    distance: int


class Neighbourhood(DomainModel):
    """The elements within a distance of some centers, and the arcs between them.

    ``cut`` is true when the size cap stopped the exploration: more elements exist at a distance
    not above ``depth``.
    """

    centers: tuple[str, ...]
    depth: int
    elements: tuple[DistantElement, ...]
    arcs: tuple[ArcView, ...]
    cut: bool


class IndexRange(DomainModel):
    """The values taken by one number in a family of names."""

    min: int
    max: int
    distinct: int
    # Set when every value is written with this many digits and some has a leading zero.
    width: int | None = None


class NameGroup(DomainModel):
    """A family of names that differ only by numbers, such as ``fork_1`` to ``fork_5``.

    ``pattern`` writes each number as ``{}``; ``indices`` gives one range per ``{}``. It is a
    description: the ids to use are those of ``/places`` and ``/transitions``.
    """

    kind: Literal["place", "transition"]
    pattern: str
    count: int
    indices: tuple[IndexRange, ...]
    example: ElementRef


def ref_of(*, node: StructureNode) -> ElementRef:
    """Cite a node."""
    return ElementRef(id=node.id, name=node.name, kind=node.kind)


def size_category(*, structure: NetStructure) -> Literal["small", "medium", "large", "huge"]:
    """Classify a net by its number of places plus transitions."""
    size = len(structure.places) + len(structure.transitions)
    if size <= SMALL_NET_MAX:
        return "small"
    if size <= MEDIUM_NET_MAX:
        return "medium"
    return "large" if size <= LARGE_NET_MAX else "huge"


def overview(*, summary: NetSummary, structure: NetStructure) -> NetOverview:
    """Build the overview of a net from its summary and structure."""
    weighted = None
    if structure.kind == "pt":
        weighted = any((arc.weight or 1) > 1 for arc in structure.arcs)
    return NetOverview(
        summary=summary,
        size_category=size_category(structure=structure),
        has_weighted_arcs=weighted,
        has_reference_nodes=structure.has_reference_nodes,
    )


def name_groups(*, structure: NetStructure, min_count: int) -> tuple[NameGroup, ...]:
    """Group places and transitions whose display names differ only by numbers.

    A node without a name is displayed by its id. Families smaller than ``min_count`` are left
    out. Digit runs of the name become the indices; the literal text between them is the key.
    """
    families: dict[tuple[str, tuple[str, ...]], list[tuple[StructureNode, tuple[str, ...]]]] = {}
    for node in (*structure.places, *structure.transitions):
        display = node.name if node.name is not None else node.id
        literals = tuple(DIGITS.split(display))
        numbers = tuple(DIGITS.findall(display))
        if not numbers:
            continue
        families.setdefault((node.kind, literals), []).append((node, numbers))

    groups: list[NameGroup] = []
    for (kind, literals), members in families.items():
        if len(members) < min_count:
            continue
        ranges = []
        for position in range(len(literals) - 1):
            written = [numbers[position] for _, numbers in members]
            values = [int(text) for text in written]
            lengths = {len(text) for text in written}
            padded = any(len(text) > 1 and text.startswith("0") for text in written)
            ranges.append(
                IndexRange(
                    min=min(values),
                    max=max(values),
                    distinct=len(set(values)),
                    width=lengths.pop() if padded and len(lengths) == 1 else None,
                )
            )
        groups.append(
            NameGroup(
                kind=kind,
                pattern="{}".join(literals),
                count=len(members),
                indices=tuple(ranges),
                example=ref_of(node=members[0][0]),
            )
        )
    return tuple(sorted(groups, key=lambda group: (group.kind, group.pattern)))


def closest_ids(*, element_id: str, ids: tuple[str, ...]) -> tuple[str, ...]:
    """Return up to five ids that look like ``element_id``: containing it, else similar to it."""
    lowered = element_id.lower()
    close = tuple(known for known in ids if lowered and lowered in known.lower())[:5]
    if not close and len(ids) <= SUGGESTION_SCAN_LIMIT:
        close = tuple(difflib.get_close_matches(element_id, ids, n=5))
    return close


def unknown_element(*, element_id: str, structure: NetStructure) -> NotFoundError:
    """Build the error for an id the net does not have, with the closest ids as a hint."""
    ids = tuple(node.id for node in (*structure.places, *structure.transitions))
    close = closest_ids(element_id=element_id, ids=ids)
    hint = f"; closest ids: {', '.join(close)}" if close else ""
    return NotFoundError(f"Unknown element {element_id!r} in net {structure.net_id}{hint}")


def neighbourhood(
    *, structure: NetStructure, centers: tuple[str, ...], depth: int, max_elements: int
) -> Neighbourhood:
    """Explore the net around ``centers``, ignoring the direction of arcs.

    Elements are added by increasing distance and, at equal distance, by id, so the result is
    deterministic; once ``max_elements`` are collected the exploration stops and ``cut`` is set.

    Raises:
        NotFoundError: if a center is not a place or transition of the net.
    """
    nodes = {node.id: node for node in (*structure.places, *structure.transitions)}
    for center in centers:
        if center not in nodes:
            raise unknown_element(element_id=center, structure=structure)
    around: dict[str, list[str]] = {}
    for arc in structure.arcs:
        around.setdefault(arc.source, []).append(arc.target)
        around.setdefault(arc.target, []).append(arc.source)

    distance: dict[str, int] = {}
    cut = False
    frontier = sorted(set(centers))
    for center in frontier:
        if len(distance) >= max_elements:
            cut = True
            break
        distance[center] = 0
    for step in range(1, depth + 1):
        reached = sorted(
            {other for node in frontier for other in around.get(node, ())} - distance.keys()
        )
        frontier = []
        for node in reached:
            if len(distance) >= max_elements:
                cut = True
                break
            distance[node] = step
            frontier.append(node)
        if cut or not frontier:
            break

    arcs = tuple(
        ArcView(
            id=arc.id,
            source=ref_of(node=nodes[arc.source]),
            target=ref_of(node=nodes[arc.target]),
            weight=arc.weight,
        )
        for arc in structure.arcs
        if arc.source in distance and arc.target in distance
    )
    elements = tuple(
        DistantElement(element=ref_of(node=nodes[node_id]), distance=step)
        for node_id, step in sorted(distance.items(), key=lambda item: (item[1], item[0]))
    )
    return Neighbourhood(centers=centers, depth=depth, elements=elements, arcs=arcs, cut=cut)
