"""A net being reduced: a private, mutable copy that rules rewrite step by step.

The reduction rules rewrite a net many times (a rule runs to a fixpoint). Copying an immutable
structure at each step would make that quadratic, so a rule works on this private copy, which is
never given out: ``structure()`` turns it back into an immutable ``NetStructure``.
"""

from __future__ import annotations

from app.domain.net_structure import NetStructure, StructureArc, StructureNode


class WorkingNet:
    """Places, transitions and weighted arcs of a P/T net, indexed both ways."""

    def __init__(self, *, structure: NetStructure) -> None:
        """Copy a structure into mutable indexes."""
        self.net_id = structure.net_id
        self.kind = structure.kind
        self.places: dict[str, StructureNode] = {p.id: p for p in structure.places}
        self.tokens: dict[str, int] = {p.id: p.tokens or 0 for p in structure.places}
        self.transitions: dict[str, StructureNode] = {t.id: t for t in structure.transitions}
        self.pre: dict[str, dict[str, int]] = {t: {} for t in self.transitions}
        self.post: dict[str, dict[str, int]] = {t: {} for t in self.transitions}
        self.consumers: dict[str, set[str]] = {p: set() for p in self.places}
        self.producers: dict[str, set[str]] = {p: set() for p in self.places}
        self.arc_ids: dict[tuple[str, str], str] = {}
        for arc in structure.arcs:
            weight = arc.weight or 1
            self.arc_ids[(arc.source, arc.target)] = arc.id
            if arc.source in self.places:
                self.pre[arc.target][arc.source] = weight
                self.consumers[arc.source].add(arc.target)
            else:
                self.post[arc.source][arc.target] = weight
                self.producers[arc.target].add(arc.source)

    def remove_transition(self, *, transition: str) -> None:
        """Remove a transition and its arcs."""
        for place in self.pre.pop(transition):
            self.consumers[place].discard(transition)
        for place in self.post.pop(transition):
            self.producers[place].discard(transition)
        del self.transitions[transition]

    def remove_place(self, *, place: str) -> None:
        """Remove a place and its arcs."""
        for transition in self.consumers.pop(place):
            del self.pre[transition][place]
        for transition in self.producers.pop(place):
            del self.post[transition][place]
        del self.places[place]
        del self.tokens[place]

    def neighbourhood(self, *, ids: set[str]) -> set[str]:
        """Return the elements given and every element joined to one of them by an arc."""
        around = set(ids)
        for identifier in ids:
            if identifier in self.transitions:
                around |= self.pre[identifier].keys() | self.post[identifier].keys()
            else:
                around |= self.consumers[identifier] | self.producers[identifier]
        return around

    def move_output(self, *, transition: str, old: str, new: str) -> None:
        """Make a transition put in ``new`` the tokens it put in ``old`` (added to what it had)."""
        weight = self.post[transition].pop(old)
        self.producers[old].discard(transition)
        self.post[transition][new] = self.post[transition].get(new, 0) + weight
        self.producers[new].add(transition)

    def add_output(self, *, transition: str, place: str, weight: int) -> None:
        """Make a transition put ``weight`` more tokens in a place."""
        self.post[transition][place] = self.post[transition].get(place, 0) + weight
        self.producers[place].add(transition)

    def structure(self) -> NetStructure:
        """Freeze the net: nodes sorted by id, an arc keeping its id when its ends are unchanged."""
        arcs = []
        for transition in self.transitions:
            for place, weight in self.pre[transition].items():
                arcs.append(self.arc(source=place, target=transition, weight=weight))
            for place, weight in self.post[transition].items():
                arcs.append(self.arc(source=transition, target=place, weight=weight))
        return NetStructure(
            net_id=self.net_id,
            kind=self.kind,
            places=tuple(
                self.places[p].model_copy(update={"tokens": self.tokens[p]})
                for p in sorted(self.places)
            ),
            transitions=tuple(self.transitions[t] for t in sorted(self.transitions)),
            arcs=tuple(sorted(arcs, key=lambda arc: arc.id)),
            has_reference_nodes=False,
        )

    def arc(self, *, source: str, target: str, weight: int) -> StructureArc:
        """Build the arc between two nodes, with its original id when it had one."""
        identifier = self.arc_ids.get((source, target), f"{source}->{target}")
        return StructureArc(id=identifier, source=source, target=target, weight=weight)
