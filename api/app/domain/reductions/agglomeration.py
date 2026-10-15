"""Rules ``pre-agglomeration`` and ``post-agglomeration`` (Berthelot, 1987).

A place ``p`` that starts empty and acts as a one-step buffer can be removed by fusing the
transitions that fill it with the ones that empty it. In *pre*-agglomeration the consumers of
``p`` need nothing else, so they can always fire right after a producer; in *post*-agglomeration
the producers put tokens nowhere but in ``p``, so they can always be delayed until a consumer is
ready. Either way the intermediate markings with a token in ``p`` disappear, and everything that
does not depend on them is kept (deadlocks, liveness, the markings of places no fused transition
touches). A formula about a place or transition next to the fused ones could see the difference,
so the rules require every such element to be unprotected.

Only the cases where the fusion does not multiply transitions are applied: one producer or one
consumer.
"""

from __future__ import annotations

from app.domain.net_structure import NetStructure

from .driver import Expand, Step, reduce_with
from .result import ReductionComputation, ReductionParameters
from .working import WorkingNet

AGGLOMERATION_PRESERVES = (
    "reachability_of_protected",
    "deadlock_freedom",
    "liveness",
    "ltl_without_next",
)


def buffer_candidates(*, net: WorkingNet, protected: frozenset[str]) -> list[str]:
    """List the places that may be agglomerated: empty, unit weights, no transition both ends."""
    candidates = []
    for place in sorted(net.places):
        producers = net.producers[place]
        consumers = net.consumers[place]
        if (
            net.tokens[place] != 0
            or not producers
            or not consumers
            or producers & consumers
            or any(net.post[t][place] != 1 for t in producers)
            or any(net.pre[u][place] != 1 for u in consumers)
        ):
            continue
        if protected & net.neighbourhood(ids={place, *producers, *consumers}):
            continue
        candidates.append(place)
    return candidates


def fuse(*, net: WorkingNet, first: str, second: str, place: str, into: str) -> None:
    """Make ``into`` (one of the two) do what ``first`` then ``second`` do, without ``place``.

    ``first`` fills ``place`` and ``second`` empties it: the fused transition takes what both
    take (except from ``place``) and gives what both give (except to ``place``).
    """
    pre: dict[str, int] = {}
    post: dict[str, int] = {}
    for transition in (first, second):
        for p, weight in net.pre[transition].items():
            if p != place:
                pre[p] = pre.get(p, 0) + weight
        for p, weight in net.post[transition].items():
            if p != place:
                post[p] = post.get(p, 0) + weight
    for p in list(net.pre[into]):
        net.consumers[p].discard(into)
    for p in list(net.post[into]):
        net.producers[p].discard(into)
    net.pre[into] = pre
    net.post[into] = post
    for p in pre:
        net.consumers[p].add(into)
    for p in post:
        net.producers[p].add(into)


def agglomerate(*, net: WorkingNet, protected: frozenset[str], after: bool) -> Step | None:
    """Agglomerate one place; ``after`` selects post- instead of pre-agglomeration."""
    for place in buffer_candidates(net=net, protected=protected):
        producers = sorted(net.producers[place])
        consumers = sorted(net.consumers[place])
        # Pre: consumers need nothing but ``place``. Post: producers give nothing but ``place``.
        if after:
            eligible = all(set(net.post[t]) == {place} for t in producers)
        else:
            eligible = all(set(net.pre[u]) == {place} for u in consumers)
        if not eligible:
            continue
        if len(consumers) == 1:
            # The single consumer is absorbed by each producer, which keeps its id.
            second = consumers[0]
            pairs = [(t, second, t) for t in producers]
            gone = second
        elif len(producers) == 1:
            # The single producer is absorbed by each consumer, which keeps its id.
            first = producers[0]
            pairs = [(first, u, u) for u in consumers]
            gone = first
        else:
            continue
        expansions = tuple(Expand(transition=into, replaces=(a, b)) for a, b, into in pairs)
        for a, b, into in pairs:
            fuse(net=net, first=a, second=b, place=place, into=into)
        net.remove_transition(transition=gone)
        net.remove_place(place=place)
        return Step(removed=(place, gone), expansions=expansions)
    return None


def pre_agglomerate(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Agglomerate a place whose consumers take nothing else."""
    return agglomerate(net=net, protected=protected, after=False)


def post_agglomerate(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Agglomerate a place whose producers give nothing else."""
    return agglomerate(net=net, protected=protected, after=True)


def pre_agglomeration(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Remove a buffer place whose consumers take nothing else, fusing them with its producers."""
    return reduce_with(
        rule_name="pre-agglomeration",
        preserves=AGGLOMERATION_PRESERVES,
        rule=pre_agglomerate,
        structure=structure,
        parameters=parameters,
    )


def post_agglomeration(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Remove a buffer place whose producers give nothing else, fusing them with its consumers."""
    return reduce_with(
        rule_name="post-agglomeration",
        preserves=AGGLOMERATION_PRESERVES,
        rule=post_agglomerate,
        structure=structure,
        parameters=parameters,
    )
