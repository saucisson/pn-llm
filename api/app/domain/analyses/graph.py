"""Reachability in the arc graph of a net, shared by the analyses."""

from __future__ import annotations

from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure


class Adjacency(DomainModel):
    """The arcs of a net as successor and predecessor sets of node ids."""

    forward: dict[str, frozenset[str]]
    backward: dict[str, frozenset[str]]


def adjacency(*, structure: NetStructure) -> Adjacency:
    """Index the arcs of a net both ways."""
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for arc in structure.arcs:
        forward.setdefault(arc.source, set()).add(arc.target)
        backward.setdefault(arc.target, set()).add(arc.source)
    return Adjacency(
        forward={k: frozenset(v) for k, v in forward.items()},
        backward={k: frozenset(v) for k, v in backward.items()},
    )


def reachable(*, start: str, edges: dict[str, frozenset[str]]) -> frozenset[str]:
    """Return the nodes reachable from ``start`` (itself included) along ``edges``."""
    seen = {start}
    pending = [start]
    while pending:
        for following in edges.get(pending.pop(), ()):
            if following not in seen:
                seen.add(following)
                pending.append(following)
    return frozenset(seen)
