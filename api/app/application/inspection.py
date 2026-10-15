"""Use cases that let a client, and the LLM, learn about a net without reading it (ADR 0013)."""

from __future__ import annotations

import fnmatch

from app.domain.contract import ElementRef, MarkingEntry, PageRequest
from app.domain.errors import InvalidRequestError
from app.domain.inspection import (
    DETAIL_LINK_LIMIT,
    MAX_NEIGHBOURHOOD_DEPTH,
    MAX_NEIGHBOURHOOD_NODES,
    ArcView,
    ElementDetail,
    NameGroup,
    Neighbourhood,
    Neighbours,
    NetOverview,
    WeightedRef,
    name_groups,
    neighbourhood,
    overview,
    ref_of,
    unknown_element,
)
from app.domain.net_structure import NetStructure, StructureNode, build_structure
from app.domain.pagination import Paged, paginate

from .ports import NetRepository


def matches(*, node: StructureNode, pattern: str | None) -> bool:
    """Tell whether a node's name matches a glob (case-sensitive); no pattern matches all."""
    if pattern is None:
        return True
    return node.name is not None and fnmatch.fnmatchcase(node.name, pattern)


class InspectionService:
    """Read-only questions about a stored net."""

    def __init__(self, *, nets: NetRepository) -> None:
        """Create the service over the net repository."""
        self._nets = nets

    def structure(self, *, net_id: str) -> NetStructure:
        """Return the flattened graph of a stored net.

        Raises:
            NotFoundError: if the net is unknown.
        """
        stored = self._nets.load_net(net_id=net_id)
        return build_structure(document=stored.document, net_id=net_id)

    def overview(self, *, net_id: str) -> NetOverview:
        """Return the counts and structural flags of a net."""
        stored = self._nets.load_net(net_id=net_id)
        structure = build_structure(document=stored.document, net_id=net_id)
        return overview(summary=stored.summary, structure=structure)

    def places(
        self, *, net_id: str, name: str | None, marked: bool | None, page: PageRequest
    ) -> Paged[ElementRef]:
        """List places, optionally by name glob and by whether they hold tokens initially.

        Raises:
            InvalidRequestError: if ``marked`` is asked of a net that is not P/T.
        """
        structure = self.structure(net_id=net_id)
        if marked is not None and structure.kind != "pt":
            raise InvalidRequestError("The marked filter needs a P/T net: other markings are terms")
        chosen = tuple(
            ref_of(node=node)
            for node in structure.places
            if matches(node=node, pattern=name)
            and (marked is None or ((node.tokens or 0) > 0) == marked)
        )
        return paginate(items=chosen, request=page)

    def transitions(self, *, net_id: str, name: str | None, page: PageRequest) -> Paged[ElementRef]:
        """List transitions, optionally by name glob."""
        structure = self.structure(net_id=net_id)
        chosen = tuple(
            ref_of(node=node) for node in structure.transitions if matches(node=node, pattern=name)
        )
        return paginate(items=chosen, request=page)

    def arcs(
        self, *, net_id: str, source: str | None, target: str | None, page: PageRequest
    ) -> Paged[ArcView]:
        """List arcs, optionally from a given source or to a given target (element ids)."""
        structure = self.structure(net_id=net_id)
        nodes = {node.id: node for node in (*structure.places, *structure.transitions)}
        for wanted in (source, target):
            if wanted is not None and wanted not in nodes:
                raise unknown_element(element_id=wanted, structure=structure)
        chosen = tuple(
            ArcView(
                id=arc.id,
                source=ref_of(node=nodes[arc.source]),
                target=ref_of(node=nodes[arc.target]),
                weight=arc.weight,
            )
            for arc in structure.arcs
            if (source is None or arc.source == source) and (target is None or arc.target == target)
        )
        return paginate(items=chosen, request=page)

    def element(self, *, net_id: str, element_id: str) -> ElementDetail:
        """Describe one place or transition: its name, tokens and the arcs around it.

        Raises:
            NotFoundError: if the id is not a place or transition (the message suggests ids).
        """
        structure = self.structure(net_id=net_id)
        nodes = {node.id: node for node in (*structure.places, *structure.transitions)}
        node = nodes.get(element_id)
        if node is None:
            raise unknown_element(element_id=element_id, structure=structure)
        incoming = tuple(
            WeightedRef(arc_id=arc.id, element=ref_of(node=nodes[arc.source]), weight=arc.weight)
            for arc in structure.arcs
            if arc.target == element_id
        )
        outgoing = tuple(
            WeightedRef(arc_id=arc.id, element=ref_of(node=nodes[arc.target]), weight=arc.weight)
            for arc in structure.arcs
            if arc.source == element_id
        )
        return ElementDetail(
            element=ref_of(node=node),
            tokens=node.tokens,
            inputs=Neighbours(items=incoming[:DETAIL_LINK_LIMIT], total=len(incoming)),
            outputs=Neighbours(items=outgoing[:DETAIL_LINK_LIMIT], total=len(outgoing)),
        )

    def search(self, *, net_id: str, query: str, page: PageRequest) -> Paged[ElementRef]:
        """Find places and transitions whose name or id matches ``query``.

        The match ignores case. ``*`` and ``?`` are wildcards; without any, the query is looked
        for anywhere in the name or id.
        """
        structure = self.structure(net_id=net_id)
        lowered = query.lower()
        pattern = lowered if {"*", "?"} & set(lowered) else f"*{lowered}*"
        chosen = tuple(
            ref_of(node=node)
            for node in sorted((*structure.places, *structure.transitions), key=lambda n: n.id)
            if fnmatch.fnmatchcase(node.id.lower(), pattern)
            or (node.name is not None and fnmatch.fnmatchcase(node.name.lower(), pattern))
        )
        return paginate(items=chosen, request=page)

    def marking(self, *, net_id: str, page: PageRequest) -> Paged[MarkingEntry]:
        """List the places holding tokens initially, with their count.

        Raises:
            InvalidRequestError: if the net is not P/T.
        """
        structure = self.structure(net_id=net_id)
        if structure.kind != "pt":
            raise InvalidRequestError("An integer marking exists only for P/T nets")
        chosen = tuple(
            MarkingEntry(place=ref_of(node=node), tokens=node.tokens or 0)
            for node in structure.places
            if (node.tokens or 0) > 0
        )
        return paginate(items=chosen, request=page)

    def neighbourhood(
        self, *, net_id: str, ids: tuple[str, ...], depth: int, max_elements: int
    ) -> Neighbourhood:
        """Explore around some elements, within the bounds of depth and size.

        Raises:
            InvalidRequestError: if no id is given or a bound is out of range.
        """
        if not ids:
            raise InvalidRequestError("At least one element id is required")
        if not 0 <= depth <= MAX_NEIGHBOURHOOD_DEPTH:
            raise InvalidRequestError(f"depth must be between 0 and {MAX_NEIGHBOURHOOD_DEPTH}")
        if not 1 <= max_elements <= MAX_NEIGHBOURHOOD_NODES:
            raise InvalidRequestError(
                f"max_elements must be between 1 and {MAX_NEIGHBOURHOOD_NODES}"
            )
        structure = self.structure(net_id=net_id)
        return neighbourhood(
            structure=structure, centers=ids, depth=depth, max_elements=max_elements
        )

    def name_groups(self, *, net_id: str, min_count: int, page: PageRequest) -> Paged[NameGroup]:
        """List families of indexed names, compressed to pattern, ranges and count."""
        structure = self.structure(net_id=net_id)
        return paginate(items=name_groups(structure=structure, min_count=min_count), request=page)
