import random

import pytest

from app.domain.catalog import OPERATIONS
from app.domain.errors import InvalidRequestError
from app.domain.operations import compute_on
from app.domain.reductions.result import ReductionParameters
from tests.reduction_oracle import explore, project, random_net, structure_of

REDUCTIONS = [op for op in OPERATIONS if op.kind == "reduction"]


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


# ---- the claim of every rule, checked on the state spaces of random nets ---------------------


@pytest.mark.parametrize("definition", REDUCTIONS, ids=lambda d: d.name)
def test_a_reduction_preserves_what_it_says_it_preserves_on_random_nets(definition):
    checked = 0
    changed = 0
    for seed in range(300):
        structure = random_net(seed=seed)
        original = explore(structure=structure)
        if original is None:
            continue
        rng = random.Random(seed)  # noqa: S311 - a seeded generator for test nets, not for secrets
        every = place_ids(structure) + transition_ids(structure)
        protected = rng.sample(every, rng.randint(0, min(2, len(every))))
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
        if "reachability" in result.preserves:
            assert project(markings=original[0], structure=structure, onto=kept) == project(
                markings=reduced[0], structure=outcome.reduced, onto=kept
            ), (definition.name, seed)
        if "deadlock_freedom" in result.preserves:
            assert bool(original[1]) == bool(reduced[1]), (definition.name, seed)
        checked += 1
    assert changed >= 10, f"{definition.name}: only {changed} random nets exercised the rule"
    assert checked == changed
