"""Rules that fuse things in series: ``fuse-series-places`` and ``fuse-series-transitions``.

Berthelot, "Transformations and decompositions of nets" (1987): a chain through a single
transition can be shortened. Firing the middle transition is invisible when nothing around it is
observed, so the reduced net keeps what the original does up to those invisible steps. Both rules
therefore insist that nothing observed is next to the elements they fuse; a formula about a
neighbour could tell the intermediate state from the fused one.
"""

from __future__ import annotations

from app.domain.net_structure import NetStructure

from .driver import Expand, Merge, Step, reduce_with
from .result import ReductionComputation, ReductionParameters
from .working import WorkingNet

SERIES_PRESERVES = (
    "reachability_of_protected",
    "deadlock_freedom",
    "liveness",
    "ltl_without_next",
)


def fuse_series_place(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Remove a place that only passes its tokens, one by one, to the next place.

    Applies to a transition ``t`` that takes one token from a place ``p`` and puts one in a place
    ``q``, when ``t`` is the only consumer of ``p`` and ``p`` starts empty: every token put in
    ``p`` can move to ``q`` at once. The producers of ``p`` then put in ``q`` directly, ``p`` and
    ``t`` disappear, and a firing of a producer stands for the producer followed by ``t``.
    """
    for transition in sorted(net.transitions):
        if len(net.pre[transition]) != 1 or len(net.post[transition]) != 1:
            continue
        (place, taken), (target, given) = (
            next(iter(net.pre[transition].items())),
            next(iter(net.post[transition].items())),
        )
        if (
            taken != 1
            or given != 1
            or place == target
            or net.consumers[place] != {transition}
            or net.tokens[place] != 0
        ):
            continue
        around = net.neighbourhood(ids={place, target, transition})
        if protected & around:
            continue
        producers = sorted(net.producers[place])
        weights = {x: net.post[x][place] for x in producers}
        for producer in producers:
            net.move_output(transition=producer, old=place, new=target)
        net.remove_transition(transition=transition)
        net.remove_place(place=place)
        return Step(
            removed=(place, transition),
            merges=(Merge(merged=(place,), into=target),),
            expansions=tuple(
                Expand(transition=x, replaces=(x, *((transition,) * weights[x]))) for x in producers
            ),
        )
    return None


def fuse_series_transition(*, net: WorkingNet, protected: frozenset[str]) -> Step | None:
    """Remove a place that links two transitions in a chain, and the second transition.

    Applies to a place ``p`` that starts empty, is filled by exactly one transition ``t1`` (one
    token) and emptied by exactly one transition ``t2`` (one token) that takes nothing else:
    ``t2`` can always fire right after ``t1``. ``t1`` then also does what ``t2`` did, and a
    firing of ``t1`` stands for ``t1`` followed by ``t2``.
    """
    for place in sorted(net.places):
        if len(net.producers[place]) != 1 or len(net.consumers[place]) != 1 or net.tokens[place]:
            continue
        first = next(iter(net.producers[place]))
        second = next(iter(net.consumers[place]))
        if first == second or net.post[first][place] != 1 or net.pre[second] != {place: 1}:
            continue
        around = net.neighbourhood(ids={place, first, second}) | net.neighbourhood(
            ids={first, second}
        )
        if protected & around:
            continue
        for target, weight in sorted(net.post[second].items()):
            net.add_output(transition=first, place=target, weight=weight)
        del net.post[first][place]
        net.producers[place].discard(first)
        net.remove_transition(transition=second)
        net.remove_place(place=place)
        return Step(
            removed=(place, second),
            expansions=(Expand(transition=first, replaces=(first, second)),),
        )
    return None


def fuse_series_places(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Remove places that only pass their tokens on to the next place."""
    return reduce_with(
        rule_name="fuse-series-places",
        preserves=SERIES_PRESERVES,
        rule=fuse_series_place,
        structure=structure,
        parameters=parameters,
    )


def fuse_series_transitions(
    *, structure: NetStructure, parameters: ReductionParameters
) -> ReductionComputation:
    """Fuse a transition into the one that always fires right before it."""
    return reduce_with(
        rule_name="fuse-series-transitions",
        preserves=SERIES_PRESERVES,
        rule=fuse_series_transition,
        structure=structure,
        parameters=parameters,
    )
