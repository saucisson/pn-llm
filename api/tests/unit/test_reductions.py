import random

import pytest

from app.domain.catalog import OPERATIONS
from app.domain.errors import InvalidRequestError
from app.domain.operations import compute_on
from app.domain.reductions.result import ReductionParameters
from tests.reduction_oracle import explore, project, random_net, structure_of

# The unfolding is tested on colored nets (test_unfolding): these rules rewrite P/T structures.
REDUCTIONS = [op for op in OPERATIONS if op.kind == "reduction" and not op.uses_document]


def reduce_net(*, rule, structure, protected=(), **parameters):
    definition = next(op for op in REDUCTIONS if op.name == rule)
    return compute_on(
        definition=definition,
        structure=structure,
        parameters={"protected": list(protected), **parameters},
    )


def ids(refs):
    return [ref.id for ref in refs]


def place_ids(structure):
    return [p.id for p in structure.places]


def transition_ids(structure):
    return [t.id for t in structure.transitions]


# ---- the mechanism: protected elements, nothing to do, bounds on the request ----------------

TWIN_PLACES = structure_of(
    places=["a", "b", "q"],
    transitions=["t", "u"],
    arcs=[("a", "t"), ("b", "t"), ("t", "q"), ("q", "u"), ("u", "a"), ("u", "b")],
    marking={"a": 1, "b": 1},
)
TWIN_TRANSITIONS = structure_of(
    places=["p", "q"],
    transitions=["t", "t_copy"],
    arcs=[("p", "t"), ("t", "q"), ("p", "t_copy"), ("t_copy", "q")],
    marking={"p": 1},
)
SELF_LOOP = structure_of(
    places=["p", "q"],
    transitions=["move", "noop"],
    arcs=[("p", "move"), ("move", "q"), ("q", "noop"), ("noop", "q")],
    marking={"p": 1},
)
DEAD = structure_of(
    places=["p", "never", "out"],
    transitions=["live", "dead"],
    arcs=[("p", "live"), ("live", "p"), ("never", "dead"), ("dead", "out")],
    marking={"p": 1},
)


def test_twin_places_are_merged_into_the_first_and_the_result_says_so():
    outcome = reduce_net(rule="fuse-parallel-places", structure=TWIN_PLACES)
    result = outcome.result
    assert (result.changed, result.applications) == (True, 1)
    assert ids(result.removed) == ["b"]
    assert [(ids(m.merged), m.into.id) for m in result.merged] == [(["b"], "a")]
    assert place_ids(outcome.reduced) == ["a", "q"]
    assert "reachability" in result.preserves


def test_a_protected_twin_is_kept_even_if_it_comes_second():
    outcome = reduce_net(rule="fuse-parallel-places", structure=TWIN_PLACES, protected=["b"])
    assert ids(outcome.result.removed) == ["a"]
    assert [(ids(m.merged), m.into.id) for m in outcome.result.merged] == [(["a"], "b")]


def test_two_protected_twins_are_both_kept_and_nothing_changes():
    outcome = reduce_net(rule="fuse-parallel-places", structure=TWIN_PLACES, protected=["a", "b"])
    assert outcome.result.changed is False
    assert outcome.reduced is None
    assert outcome.result.new_net_id is None
    assert "nowhere" in outcome.result.note


def test_twin_transitions_keep_the_first_one():
    outcome = reduce_net(rule="fuse-parallel-transitions", structure=TWIN_TRANSITIONS)
    assert ids(outcome.result.removed) == ["t_copy"]
    assert transition_ids(outcome.reduced) == ["t"]


def test_self_loop_transitions_are_removed_but_deadlock_freedom_is_not_claimed():
    outcome = reduce_net(rule="remove-self-loop-transitions", structure=SELF_LOOP)
    assert ids(outcome.result.removed) == ["noop"]
    assert "deadlock_freedom" not in outcome.result.preserves
    assert "reachability" in outcome.result.preserves


def test_dead_transitions_are_removed_with_their_arcs():
    outcome = reduce_net(rule="remove-dead-transitions", structure=DEAD)
    assert ids(outcome.result.removed) == ["dead"]
    assert [(a.source, a.target) for a in outcome.reduced.arcs] == [
        ("live", "p"),
        ("p", "live"),
    ] or sorted((a.source, a.target) for a in outcome.reduced.arcs) == [
        ("live", "p"),
        ("p", "live"),
    ]
    protected = reduce_net(rule="remove-dead-transitions", structure=DEAD, protected=["dead"])
    assert protected.result.changed is False


def test_a_rule_that_would_empty_the_net_does_nothing():
    only_dead = structure_of(places=["never"], transitions=["dead"], arcs=[("never", "dead")])
    outcome = reduce_net(rule="remove-dead-transitions", structure=only_dead)
    assert outcome.result.changed is False
    assert "no place or no transition" in outcome.result.note


def test_max_applications_stops_a_rule_that_runs_to_a_fixpoint():
    several = structure_of(
        places=["a", "b", "c", "d"],
        transitions=["t"],
        arcs=[("a", "t"), ("b", "t"), ("c", "t"), ("d", "t")],
        marking={"a": 1, "b": 1, "c": 1, "d": 1},
    )
    # One application merges every group at once, so the bound shows on rules with several steps.
    assert reduce_net(rule="fuse-parallel-places", structure=several).result.applications == 1
    bounded = reduce_net(rule="fuse-parallel-places", structure=several, max_applications=1)
    assert bounded.result.applications == 1


def test_a_protected_id_that_is_not_in_the_net_is_refused():
    with pytest.raises(InvalidRequestError, match="not in the net"):
        reduce_net(rule="fuse-parallel-places", structure=TWIN_PLACES, protected=["ghost"])


def test_the_same_set_of_protected_ids_is_the_same_request():
    one = ReductionParameters(protected=("b", "a", "a"))
    assert one.protected == ("a", "b")


# ---- series rules and implicit places -------------------------------------------------------

# a --x--> mid --t--> q --y--> a: mid only passes the token on to q.
CHAIN = structure_of(
    places=["a", "mid", "q"],
    transitions=["x", "t", "y"],
    arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("t", "q"), ("q", "y"), ("y", "a")],
    marking={"a": 1},
)


def expansions_of(result):
    return [(item.transition.id, ids(item.original)) for item in result.expansions]


def test_a_place_that_only_passes_tokens_on_is_removed_and_its_producer_stands_for_two_firings():
    outcome = reduce_net(rule="fuse-series-places", structure=CHAIN, max_applications=1)
    assert ids(outcome.result.removed) == ["mid", "t"]
    assert expansions_of(outcome.result) == [("x", ["x", "t"])]
    assert sorted((a.source, a.target) for a in outcome.reduced.arcs) == [
        ("a", "x"),
        ("q", "y"),
        ("x", "q"),
        ("y", "a"),
    ]
    # Without a bound the rule goes on: the whole loop collapses into a self-loop of x.
    everything = reduce_net(rule="fuse-series-places", structure=CHAIN)
    assert everything.result.applications == 2
    assert expansions_of(everything.result) == [("x", ["x", "t", "y"])]
    assert "reachability_of_protected" in outcome.result.preserves
    assert "ltl_without_next" in outcome.result.preserves


def test_a_protected_neighbour_stops_a_series_rule_but_a_far_element_does_not():
    assert (
        reduce_net(rule="fuse-series-places", structure=CHAIN, protected=["x"]).result.changed
        is False
    )
    assert (
        reduce_net(rule="fuse-series-places", structure=CHAIN, protected=["q"]).result.changed
        is False
    )
    far = reduce_net(
        rule="fuse-series-places", structure=CHAIN, protected=["a"], max_applications=1
    )
    assert far.result.changed is True


def test_series_places_need_an_empty_place_with_one_consumer():
    marked = structure_of(
        places=["a", "mid", "q"],
        transitions=["x", "t"],
        arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("t", "q")],
        marking={"a": 1, "mid": 1},
    )
    shared = structure_of(
        places=["a", "mid", "q"],
        transitions=["x", "t", "z"],
        arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("mid", "z"), ("t", "q")],
        marking={"a": 1},
    )
    for structure in (marked, shared):
        assert reduce_net(rule="fuse-series-places", structure=structure).result.changed is False


def test_a_producer_with_a_weighted_arc_is_followed_by_the_move_that_many_times():
    weighted = structure_of(
        places=["a", "mid", "q"],
        transitions=["x", "t"],
        arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("t", "q")],
        marking={"a": 1},
        weights={1: 2},
    )
    outcome = reduce_net(rule="fuse-series-places", structure=weighted)
    assert expansions_of(outcome.result) == [("x", ["x", "t", "t"])]
    assert {(a.source, a.target): a.weight for a in outcome.reduced.arcs}[("x", "q")] == 2


def test_two_transitions_in_a_chain_are_fused_into_the_first():
    outcome = reduce_net(rule="fuse-series-transitions", structure=CHAIN, max_applications=1)
    assert ids(outcome.result.removed) == ["mid", "t"]
    assert expansions_of(outcome.result) == [("x", ["x", "t"])]
    assert (
        reduce_net(rule="fuse-series-transitions", structure=CHAIN, protected=["a"]).result.changed
        is False
    )
    far = reduce_net(
        rule="fuse-series-transitions", structure=CHAIN, protected=["y"], max_applications=1
    )
    assert far.result.changed is True


def test_the_second_transition_must_take_nothing_but_the_chain_place():
    greedy = structure_of(
        places=["a", "mid", "extra", "q"],
        transitions=["x", "t"],
        arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("extra", "t"), ("t", "q")],
        marking={"a": 1, "extra": 1},
    )
    assert reduce_net(rule="fuse-series-transitions", structure=greedy).result.changed is False


def test_series_rules_compose_into_one_expansion_over_the_original_net():
    two_links = structure_of(
        places=["a", "m1", "m2", "q"],
        transitions=["x", "t1", "t2", "y"],
        arcs=[
            ("a", "x"),
            ("x", "m1"),
            ("m1", "t1"),
            ("t1", "m2"),
            ("m2", "t2"),
            ("t2", "q"),
            ("q", "y"),
            ("y", "a"),
        ],
        marking={"a": 1},
    )
    outcome = reduce_net(rule="fuse-series-places", structure=two_links)
    assert outcome.result.applications == 3
    assert expansions_of(outcome.result) == [("x", ["x", "t1", "t2", "y"])]


def test_a_place_nobody_consumes_is_implicit_and_so_is_one_dominated_by_another():
    sink = structure_of(
        places=["p", "q", "s"],
        transitions=["t"],
        arcs=[("p", "t"), ("t", "q"), ("t", "s")],
        marking={"p": 1},
    )
    assert ids(reduce_net(rule="remove-implicit-places", structure=sink).result.removed) == [
        "q",
        "s",
    ]
    # b always holds at least what a holds, and its consumer needs a as much as b: b is implicit.
    dominated = structure_of(
        places=["a", "b", "c"],
        transitions=["t", "u"],
        arcs=[("a", "t"), ("b", "t"), ("t", "c"), ("c", "u"), ("u", "a"), ("u", "b")],
        marking={"a": 1, "b": 2, "c": 0},
    )
    outcome = reduce_net(rule="remove-implicit-places", structure=dominated)
    assert ids(outcome.result.removed) == ["b"]
    assert "boundedness" not in outcome.result.preserves


def test_implicit_places_keep_what_a_consumer_needs_and_what_is_protected():
    needed = structure_of(
        places=["a", "b"],
        transitions=["t", "u"],
        arcs=[("a", "t"), ("t", "b"), ("b", "u"), ("u", "a")],
        marking={"a": 1},
    )
    assert reduce_net(rule="remove-implicit-places", structure=needed).result.changed is False
    sink = structure_of(
        places=["p", "s"], transitions=["t"], arcs=[("p", "t"), ("t", "s")], marking={"p": 1}
    )
    assert (
        reduce_net(rule="remove-implicit-places", structure=sink, protected=["s"]).result.changed
        is False
    )


# ---- agglomerations ---------------------------------------------------------------------------

BUFFER = structure_of(
    places=["s", "p", "r"],
    transitions=["t", "u"],
    arcs=[("s", "t"), ("t", "p"), ("p", "u"), ("u", "r")],
    marking={"s": 1},
)


def arcs_of(structure):
    return sorted((a.source, a.target, a.weight) for a in structure.arcs)


def test_pre_agglomeration_makes_each_producer_do_what_the_consumer_did():
    outcome = reduce_net(rule="pre-agglomeration", structure=BUFFER)
    assert ids(outcome.result.removed) == ["p", "u"]
    assert expansions_of(outcome.result) == [("t", ["t", "u"])]
    assert arcs_of(outcome.reduced) == [("s", "t", 1), ("t", "r", 1)]


def test_pre_agglomeration_of_one_producer_into_several_consumers_keeps_the_consumer_ids():
    branching = structure_of(
        places=["s", "p", "r1", "r2"],
        transitions=["t", "u1", "u2"],
        arcs=[("s", "t"), ("t", "p"), ("p", "u1"), ("u1", "r1"), ("p", "u2"), ("u2", "r2")],
        marking={"s": 1},
    )
    outcome = reduce_net(rule="pre-agglomeration", structure=branching)
    assert ids(outcome.result.removed) == ["p", "t"]
    assert expansions_of(outcome.result) == [("u1", ["t", "u1"]), ("u2", ["t", "u2"])]
    assert arcs_of(outcome.reduced) == [
        ("s", "u1", 1),
        ("s", "u2", 1),
        ("u1", "r1", 1),
        ("u2", "r2", 1),
    ]


def test_post_agglomeration_makes_the_consumer_wait_for_what_the_producer_needs():
    waiting = structure_of(
        places=["s", "w", "p", "r"],
        transitions=["t", "u"],
        arcs=[("s", "t"), ("t", "p"), ("p", "u"), ("w", "u"), ("u", "r")],
        marking={"s": 1, "w": 1},
    )
    # u needs w as well as p, so pre-agglomeration does not apply but post-agglomeration does.
    assert reduce_net(rule="pre-agglomeration", structure=waiting).result.changed is False
    outcome = reduce_net(rule="post-agglomeration", structure=waiting)
    assert expansions_of(outcome.result) == [("t", ["t", "u"])]
    assert arcs_of(outcome.reduced) == [("s", "t", 1), ("t", "r", 1), ("w", "t", 1)]


def test_an_agglomeration_needs_an_empty_buffer_and_no_transition_at_both_ends():
    marked = structure_of(
        places=["s", "p", "r"],
        transitions=["t", "u"],
        arcs=[("s", "t"), ("t", "p"), ("p", "u"), ("u", "r")],
        marking={"s": 1, "p": 1},
    )
    both_ends = structure_of(
        places=["s", "p", "r"],
        transitions=["t", "u"],
        arcs=[("s", "t"), ("t", "p"), ("p", "u"), ("u", "p"), ("u", "r")],
        marking={"s": 1},
    )
    for structure in (marked, both_ends):
        for rule in ("pre-agglomeration", "post-agglomeration"):
            assert reduce_net(rule=rule, structure=structure).result.changed is False


def test_an_agglomeration_leaves_alone_what_is_protected_around_the_buffer():
    for protected in (["s"], ["r"], ["t"], ["u"], ["p"]):
        assert (
            reduce_net(
                rule="pre-agglomeration", structure=BUFFER, protected=protected
            ).result.changed
            is False
        )


# ---- the claim of every rule, checked on the state spaces of random nets ---------------------


@pytest.mark.parametrize("definition", REDUCTIONS, ids=lambda d: d.name)
def test_a_reduction_preserves_what_it_says_it_preserves_on_random_nets(definition):
    checked = 0
    changed = 0
    for seed in range(500):
        structure = random_net(seed=seed)
        original = explore(structure=structure)
        if original is None:
            continue
        rng = random.Random(seed)  # noqa: S311 - a seeded generator for test nets, not for secrets
        every = place_ids(structure) + transition_ids(structure)
        protected = rng.sample(every, rng.randint(0, min(5, len(every))))
        outcome = compute_on(
            definition=definition,
            structure=structure,
            parameters={"protected": protected},
        )
        result = outcome.result
        # Domain rule 3: a protected element is never removed or merged.
        gone = set(ids(result.removed)) | {i for m in result.merged for i in ids(m.merged)}
        assert not gone & set(protected), (definition.name, seed)
        if not result.changed:
            continue
        changed += 1
        reduced = explore(structure=outcome.reduced)
        assert reduced is not None
        kept = place_ids(outcome.reduced)
        # What is compared: all the kept places for a rule that keeps them as they were, only the
        # protected ones for a rule that changes how tokens pass through unprotected places.
        onto = (
            kept
            if "reachability" in result.preserves
            else [p for p in protected if p in kept]
            if "reachability_of_protected" in result.preserves
            else []
        )
        if onto:
            assert project(markings=original[0], structure=structure, onto=onto) == project(
                markings=reduced[0], structure=outcome.reduced, onto=onto
            ), (definition.name, seed)
        if "deadlock_freedom" in result.preserves:
            assert bool(original[1]) == bool(reduced[1]), (definition.name, seed)
        checked += 1
    assert changed >= 10, f"{definition.name}: only {changed} random nets exercised the rule"
    assert checked == changed
