"""Analysis ``net-class``: which structural classes a net belongs to."""

from __future__ import annotations

from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure
from app.domain.operations import NoParameters

from .graph import adjacency, reachable


class NetClassResult(DomainModel):
    """The structural classes of a net, each decided from its arcs alone."""

    ordinary: bool
    state_machine: bool
    marked_graph: bool
    free_choice: bool
    extended_free_choice: bool
    workflow_like: bool


def net_class(*, structure: NetStructure, parameters: NoParameters) -> NetClassResult:
    """Classify a P/T net.

    State machine: every transition has one input and one output place. Marked graph: every place
    has one input and one output transition. Extended free choice: transitions sharing an input
    place have the same input places. Free choice: a place with several output transitions is the
    only input place of each. Workflow-like: one source place, one sink place, and every element
    on a path from the source to the sink. A class defined on ordinary nets is not claimed for a
    net with weighted arcs.
    """
    place_ids = {place.id for place in structure.places}
    pre: dict[str, set[str]] = {t.id: set() for t in structure.transitions}  # input places
    post: dict[str, set[str]] = {t.id: set() for t in structure.transitions}  # output places
    place_in: dict[str, set[str]] = {p: set() for p in place_ids}  # input transitions
    place_out: dict[str, set[str]] = {p: set() for p in place_ids}  # output transitions
    ordinary = True
    for arc in structure.arcs:
        ordinary = ordinary and (arc.weight in {None, 1})
        if arc.source in place_ids:
            pre[arc.target].add(arc.source)
            place_out[arc.source].add(arc.target)
        else:
            post[arc.source].add(arc.target)
            place_in[arc.target].add(arc.source)

    state_machine = ordinary and all(len(pre[t]) == 1 and len(post[t]) == 1 for t in pre)
    marked_graph = ordinary and all(
        len(place_in[p]) == 1 and len(place_out[p]) == 1 for p in place_ids
    )
    extended_free_choice = ordinary and all(
        pre[a] == pre[b] for a in pre for b in pre if pre[a] & pre[b]
    )
    free_choice = ordinary and all(
        len(place_out[p]) <= 1 or all(pre[t] == {p} for t in place_out[p]) for p in place_ids
    )

    sources = [p for p in place_ids if not place_in[p]]
    sinks = [p for p in place_ids if not place_out[p]]
    workflow_like = False
    if len(sources) == 1 and len(sinks) == 1:
        graph = adjacency(structure=structure)
        everything = place_ids | set(pre)
        workflow_like = (
            reachable(start=sources[0], edges=graph.forward) == everything
            and reachable(start=sinks[0], edges=graph.backward) == everything
        )
    return NetClassResult(
        ordinary=ordinary,
        state_machine=state_machine,
        marked_graph=marked_graph,
        free_choice=free_choice,
        extended_free_choice=extended_free_choice,
        workflow_like=workflow_like,
    )
