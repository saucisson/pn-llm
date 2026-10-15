"""Analysis ``dead-transitions``: transitions that can never fire, decided from the structure."""

from __future__ import annotations

from app.domain.contract import ElementRef
from app.domain.inspection import ref_of
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure
from app.domain.operations import NoParameters


class DeadTransitionsResult(DomainModel):
    """Transitions proven dead, and the places that can never hold a token."""

    dead_transitions: tuple[ElementRef, ...]
    never_marked_places: tuple[ElementRef, ...]
    # Not dead does not mean live: a transition left out may still never fire (weights, timing of
    # tokens); this analysis only proves what the structure shows.
    note: str = "A transition not listed is not proven live."


def dead_transitions(
    *,
    structure: NetStructure,
    parameters: NoParameters,
) -> DeadTransitionsResult:
    """Find the transitions that cannot fire because an input place can never hold a token.

    A place can be marked if it holds a token initially, or if some transition that can fire puts
    one in it; a transition can fire only if all its input places can be marked. The least
    fixpoint of these two rules over-approximates the markable places and the firable transitions,
    so what is left out is dead whatever the arc weights, the same as an unmarked siphon staying
    unmarked.
    """
    place_ids = {place.id for place in structure.places}
    inputs: dict[str, set[str]] = {t.id: set() for t in structure.transitions}
    outputs: dict[str, set[str]] = {t.id: set() for t in structure.transitions}
    for arc in structure.arcs:
        if arc.source in place_ids:
            inputs[arc.target].add(arc.source)
        else:
            outputs[arc.source].add(arc.target)
    markable = {place.id for place in structure.places if (place.tokens or 0) > 0}
    firable: set[str] = set()
    changed = True
    while changed:
        changed = False
        for transition, needed in inputs.items():
            if transition not in firable and needed <= markable:
                firable.add(transition)
                markable |= outputs[transition]
                changed = True
    return DeadTransitionsResult(
        dead_transitions=tuple(
            ref_of(node=t) for t in structure.transitions if t.id not in firable
        ),
        never_marked_places=tuple(ref_of(node=p) for p in structure.places if p.id not in markable),
    )
