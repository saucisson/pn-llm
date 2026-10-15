"""An oracle for reductions: explore the states of small nets and compare.

A reduction claims to preserve some behaviour; here the claim is checked on the whole state space
of small bounded nets, so a rule that is wrong is caught by a net, not by a proof sketch.
"""

import random

from app.domain.net_structure import NetStructure, build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml

PT = "http://www.pnml.org/version-2009/grammar/ptnet"
STATE_LIMIT = 4000


def structure_of(*, places, transitions, arcs, marking=None, weights=None):
    """Build a structure from ids: arcs are (source, target) pairs, weights by arc index."""
    marking = marking or {}
    weights = weights or {}
    parts = [f'<pnml><net id="n" type="{PT}"><page id="pg">']
    for place in places:
        tokens = marking.get(place)
        initial = f"<initialMarking><text>{tokens}</text></initialMarking>" if tokens else ""
        parts.append(f'<place id="{place}"><name><text>{place}</text></name>{initial}</place>')
    for transition in transitions:
        parts.append(
            f'<transition id="{transition}"><name><text>{transition}</text></name></transition>'
        )
    for index, (source, target) in enumerate(arcs):
        weight = weights.get(index)
        inscription = f"<inscription><text>{weight}</text></inscription>" if weight else ""
        parts.append(f'<arc id="a{index}" source="{source}" target="{target}">{inscription}</arc>')
    parts.append("</page></net></pnml>")
    document = import_pnml(payload="".join(parts).encode(), limits=DocumentLimits())
    return build_structure(document=document, net_id="n")


def explore(*, structure: NetStructure):
    """Return (markings, deadlocks) reachable, or None if the state space is larger than the limit.

    A marking is a tuple of tokens in the order of ``structure.places``.
    """
    index = {p.id: i for i, p in enumerate(structure.places)}
    pre = {t.id: {} for t in structure.transitions}
    post = {t.id: {} for t in structure.transitions}
    for arc in structure.arcs:
        if arc.source in index:
            pre[arc.target][index[arc.source]] = arc.weight or 1
        else:
            post[arc.source][index[arc.target]] = arc.weight or 1
    start = tuple(p.tokens or 0 for p in structure.places)
    seen = {start}
    pending = [start]
    deadlocks = set()
    while pending:
        marking = pending.pop()
        fired = False
        for transition, needs in pre.items():
            if all(marking[p] >= w for p, w in needs.items()):
                fired = True
                nxt = list(marking)
                for p, w in needs.items():
                    nxt[p] -= w
                for p, w in post[transition].items():
                    nxt[p] += w
                nxt_t = tuple(nxt)
                if nxt_t not in seen:
                    if len(seen) >= STATE_LIMIT:
                        return None
                    seen.add(nxt_t)
                    pending.append(nxt_t)
        if not fired:
            deadlocks.add(marking)
    return seen, deadlocks


def project(*, markings, structure: NetStructure, onto):
    """Project markings on the places in ``onto``, as sets of (place, tokens) tuples."""
    index = {p.id: i for i, p in enumerate(structure.places)}
    keep = sorted(onto)
    return {tuple((p, m[index[p]]) for p in keep) for m in markings}


def random_net(*, seed: int):
    """A small random P/T net, seeded, with some duplicated places and transitions."""
    rng = random.Random(seed)  # noqa: S311 - a seeded generator for test nets, not for secrets
    places = [f"p{i}" for i in range(rng.randint(2, 6))]
    transitions = [f"t{i}" for i in range(rng.randint(1, 5))]
    arcs, weights = [], {}
    for t in transitions:
        for p in rng.sample(places, rng.randint(0, min(2, len(places)))):
            weights[len(arcs)] = rng.choice([None, None, None, 2])
            arcs.append((p, t))
        for p in rng.sample(places, rng.randint(0, min(2, len(places)))):
            weights[len(arcs)] = rng.choice([None, None, None, 2])
            arcs.append((t, p))
    # Twins make the parallel rules apply often enough to be tested.
    if rng.random() < 0.5:
        twin_of = rng.choice(places)
        twin = f"{twin_of}_twin"
        for source, target in list(arcs):
            if source == twin_of:
                arcs.append((twin, target))
                weights[len(arcs) - 1] = weights.get(arcs.index((source, target)))
            elif target == twin_of:
                arcs.append((source, twin))
                weights[len(arcs) - 1] = weights.get(arcs.index((source, target)))
        places.append(twin)
    if rng.random() < 0.5 and transitions:
        twin_t = f"{transitions[0]}_twin"
        for source, target in list(arcs):
            if source == transitions[0]:
                arcs.append((twin_t, target))
                weights[len(arcs) - 1] = weights.get(arcs.index((source, target)))
            elif target == transitions[0]:
                arcs.append((source, twin_t))
                weights[len(arcs) - 1] = weights.get(arcs.index((source, target)))
        transitions.append(twin_t)
    marking = {p: rng.randint(0, 2) for p in places if rng.random() < 0.6}
    if marking.get(places[-1]) is not None and places[-1].endswith("_twin"):
        marking[places[-1]] = marking.get(places[-1].removesuffix("_twin"), 0)
    return structure_of(
        places=places, transitions=transitions, arcs=arcs, marking=marking, weights=weights
    )
