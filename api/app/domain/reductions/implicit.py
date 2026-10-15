"""Rule ``remove-implicit-places``: a place that never keeps a transition from firing.

A place with no consumer never keeps anything from firing. A place ``p`` is also redundant when
another place ``q`` always holds no more than it does and every consumer of ``p`` needs at least as
many tokens from ``q`` as from ``p``: whenever a consumer finds its tokens in ``q`` it finds them in
``p`` (a special case of the implicit places of Colom and Silva, "Improving the linearly based
characterization of P/T nets", 1991, with a single place for the linear combination).
"""

from __future__ import annotations

from app.domain.net_structure import NetStructure

from .driver import Step, reduce_with
from .result import ReductionComputation, ReductionParameters
from .working import WorkingNet

# Boundedness is not claimed: the place removed may be the only one that grows without bound.
IMPLICIT_PRESERVES = ("reachability", "deadlock_freedom", "liveness", "ltl")


def dominated_by(*, net: WorkingNet, place: str, other: str) -> bool:
    """Tell whether ``other`` always holds at most as many tokens as ``place``.

    True when it does initially and no transition takes less from, or gives more to, ``place``
    than to ``other`` in total; then the difference of their markings never decreases.
    """
    if net.tokens[place] < net.tokens[other]:
        return False
    touching = (
        net.consumers[place] | net.producers[place] | net.consumers[other] | net.producers[other]
    )
    return all(
        net.post[t].get(place, 0) - net.pre[t].get(place, 0)
        >= net.post[t].get(other, 0) - net.pre[t].get(other, 0)
        for t in touching
    )


def remove_implicit(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Remove one unprotected place that keeps no transition from firing."""
    for place in sorted(net.places):
        if place in protected:
            continue
        consumers = sorted(net.consumers[place])
        if consumers:
            candidates = [
                q
                for q in net.pre[consumers[0]]
                if q != place and net.pre[consumers[0]][q] >= net.pre[consumers[0]][place]
            ]
            witness = next(
                (
                    q
                    for q in sorted(candidates)
                    if all(net.pre[t].get(q, 0) >= net.pre[t][place] for t in consumers)
                    and dominated_by(net=net, place=place, other=q)
                ),
                None,
            )
            if witness is None:
                continue
        net.remove_place(place=place)
        return Step(removed=(place,))
    return None


def remove_implicit_places(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Remove the places that never keep a transition from firing."""
    return reduce_with(
        rule_name="remove-implicit-places",
        preserves=IMPLICIT_PRESERVES,
        rule=remove_implicit,
        structure=structure,
        parameters=parameters,
    )
