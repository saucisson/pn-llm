from app.domain.analyses.conflict_sets import ConflictSetsParameters, conflict_sets
from app.domain.analyses.connected_components import (
    ConnectedComponentsParameters,
    connected_components,
)
from app.domain.analyses.dead_transitions import dead_transitions
from app.domain.analyses.place_bounds import PlaceBoundsParameters, place_bounds
from app.domain.analyses.siphons import (
    MinimalSiphonsParameters,
    MinimalTrapsParameters,
    minimal_siphons,
    minimal_traps,
)
from app.domain.analyses.t_invariants import TInvariantsParameters, t_invariants
from app.domain.contract import FiniteBound, UnboundedBound, UnknownBound
from app.domain.net_structure import build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.operations import NoParameters
from app.domain.pnml_import import import_pnml
from tests.support import MUTEX_PNML
from tests.unit.test_analyses import CHOICE, CONFUSION, CYCLE, FORK_OPEN, PHILOSOPHERS, net

MUTEX = build_structure(
    document=import_pnml(payload=MUTEX_PNML, limits=DocumentLimits()), net_id="n"
)
PRODUCER_CONSUMER = net(
    places=["idle_p", "busy_p", "item", "idle_c", "busy_c"],
    transitions=["produce", "deliver", "consume", "finish"],
    arcs=[
        ("idle_p", "produce"),
        ("produce", "busy_p"),
        ("busy_p", "deliver"),
        ("deliver", "idle_p"),
        ("deliver", "item"),
        ("item", "consume"),
        ("idle_c", "consume"),
        ("consume", "busy_c"),
        ("busy_c", "finish"),
        ("finish", "idle_c"),
    ],
    marking={"idle_p": 1, "idle_c": 1},
)


def ids(refs):
    return [ref.id for ref in refs]


def supports(result):
    return {frozenset(w.element.id for w in inv.elements) for inv in result.invariants}


# ---- t-invariants ----------------------------------------------------------------------------


def test_mutex_transitions_return_the_marking_together():
    result = t_invariants(structure=MUTEX, parameters=TInvariantsParameters())
    assert supports(result) == {frozenset({"enter1", "leave1"})}
    assert [w.weight for w in result.invariants[0].elements] == [1, 1]
    assert result.uncovered_transitions == ()


def test_the_producer_consumer_cycle_fires_every_transition_once():
    result = t_invariants(structure=PRODUCER_CONSUMER, parameters=TInvariantsParameters())
    assert supports(result) == {frozenset({"produce", "deliver", "consume", "finish"})}


def test_a_transition_in_no_cycle_is_reported_uncovered():
    result = t_invariants(structure=FORK_OPEN, parameters=TInvariantsParameters())
    assert result.total == 0
    assert ids(result.uncovered_transitions) == ["f", "j"]


def test_a_net_without_places_has_every_transition_in_its_own_invariant():
    isolated = net(places=[], transitions=["a", "b"], arcs=[])
    result = t_invariants(structure=isolated, parameters=TInvariantsParameters())
    assert supports(result) == {frozenset({"a"}), frozenset({"b"})}


# ---- place-bounds ---------------------------------------------------------------------------


def test_places_in_a_marked_invariant_are_bounded_by_its_constant():
    result = place_bounds(structure=MUTEX, parameters=PlaceBoundsParameters())
    assert {b.place.id: b.bound for b in result.bounds} == {
        "crit1": FiniteBound(value=1),
        "idle1": FiniteBound(value=1),
        "lock": FiniteBound(value=1),
    }
    assert (result.finite, result.unbounded, result.unknown) == (3, 0, 0)
    assert result.largest_finite_bound == 1


def test_a_weighted_invariant_bounds_by_integer_division():
    # a + 2b is constant at 3 (a=3): b <= 1, a <= 3.
    structure = net(
        places=["a", "b"],
        transitions=["t", "u"],
        arcs=[("a", "t"), ("t", "b"), ("b", "u"), ("u", "a")],
        weights={0: 2, 3: 2},
        marking={"a": 3},
    )
    bounds = {
        b.place.id: b.bound
        for b in place_bounds(structure=structure, parameters=PlaceBoundsParameters()).bounds
    }
    assert bounds == {"a": FiniteBound(value=3), "b": FiniteBound(value=1)}


def test_a_place_outside_every_invariant_is_unknown_and_a_fed_one_unbounded():
    result = place_bounds(structure=PRODUCER_CONSUMER, parameters=PlaceBoundsParameters())
    assert {b.place.id: b.bound for b in result.bounds}["item"] == UnknownBound()
    source = net(
        places=["p", "q"],
        transitions=["gen", "use"],
        arcs=[("gen", "p"), ("p", "use"), ("use", "q")],
    )
    bounds = {
        b.place.id: b.bound
        for b in place_bounds(structure=source, parameters=PlaceBoundsParameters()).bounds
    }
    assert bounds["p"] == UnboundedBound()
    assert bounds["q"] == UnknownBound()  # fed by a transition that needs p: not proven


def test_the_listing_is_capped_but_the_counts_cover_every_place():
    result = place_bounds(structure=MUTEX, parameters=PlaceBoundsParameters(max_places=1))
    assert (len(result.bounds), result.total, result.finite) == (1, 3, 3)


def test_when_the_invariant_search_stops_nothing_is_claimed_bounded():
    result = place_bounds(structure=PHILOSOPHERS, parameters=PlaceBoundsParameters(max_rows=1))
    assert result.complete is False
    assert result.finite == 0


# ---- siphons and traps -----------------------------------------------------------------------


def place_set_ids(result):
    return {frozenset(ids(s.places)) for s in result.sets}


def test_the_mutex_siphons_and_traps_are_its_two_invariant_supports():
    expected = {frozenset({"crit1", "idle1"}), frozenset({"crit1", "lock"})}
    siphons = minimal_siphons(structure=MUTEX, parameters=MinimalSiphonsParameters())
    traps = minimal_traps(structure=MUTEX, parameters=MinimalTrapsParameters())
    assert place_set_ids(siphons) == expected == place_set_ids(traps)
    assert all(s.initially_marked for s in siphons.sets)
    assert siphons.complete is True


def test_an_unmarked_siphon_is_flagged():
    # p1 -> t -> p2 -> u -> p1 with no token: {p1, p2} is a siphon that never gets marked.
    dead = net(
        places=["p1", "p2"],
        transitions=["t", "u"],
        arcs=[("p1", "t"), ("t", "p2"), ("p2", "u"), ("u", "p1")],
    )
    siphons = minimal_siphons(structure=dead, parameters=MinimalSiphonsParameters())
    assert place_set_ids(siphons) == {frozenset({"p1", "p2"})}
    assert siphons.sets[0].initially_marked is False


def test_a_place_fed_by_a_source_transition_is_in_no_siphon_and_a_sink_place_is_a_trap():
    flow = net(
        places=["p", "q"],
        transitions=["gen", "use"],
        arcs=[("gen", "p"), ("p", "use"), ("use", "q")],
    )
    assert minimal_siphons(structure=flow, parameters=MinimalSiphonsParameters()).total == 0
    traps = minimal_traps(structure=flow, parameters=MinimalTrapsParameters())
    assert place_set_ids(traps) == {frozenset({"q"})}


def test_the_search_says_when_it_stopped_and_the_listing_is_capped():
    limited = minimal_siphons(
        structure=PHILOSOPHERS, parameters=MinimalSiphonsParameters(max_steps=1)
    )
    assert limited.complete is False
    capped = minimal_siphons(structure=MUTEX, parameters=MinimalSiphonsParameters(max_results=1))
    assert (len(capped.sets), capped.total) == (1, 2)


# ---- dead transitions ------------------------------------------------------------------------


def test_a_live_net_has_no_dead_transition():
    result = dead_transitions(structure=MUTEX, parameters=NoParameters())
    assert (result.dead_transitions, result.never_marked_places) == ((), ())


def test_dead_transitions_spread_along_the_flow():
    # p1 is never marked and nothing feeds it: t is dead, so q is never marked, so u is dead.
    structure = net(
        places=["p1", "q", "r"],
        transitions=["t", "u"],
        arcs=[("p1", "t"), ("t", "q"), ("q", "u"), ("u", "r")],
    )
    result = dead_transitions(structure=structure, parameters=NoParameters())
    assert ids(result.dead_transitions) == ["t", "u"]
    assert ids(result.never_marked_places) == ["p1", "q", "r"]


def test_a_transition_needing_two_places_is_dead_if_one_of_them_never_gets_a_token():
    structure = net(
        places=["a", "b"], transitions=["t"], arcs=[("a", "t"), ("b", "t")], marking={"a": 1}
    )
    assert ids(
        dead_transitions(structure=structure, parameters=NoParameters()).dead_transitions
    ) == ["t"]


def test_the_cycle_is_live_once_marked_and_dead_without_a_token():
    assert dead_transitions(structure=CYCLE, parameters=NoParameters()).dead_transitions == ()
    unmarked = net(
        places=["p1", "p2"],
        transitions=["t1", "t2"],
        arcs=[("p1", "t1"), ("t1", "p2"), ("p2", "t2"), ("t2", "p1")],
    )
    assert ids(
        dead_transitions(structure=unmarked, parameters=NoParameters()).dead_transitions
    ) == ["t1", "t2"]


# ---- conflict sets ---------------------------------------------------------------------------


def test_transitions_sharing_an_input_place_form_a_group_with_that_place():
    result = conflict_sets(structure=CHOICE, parameters=ConflictSetsParameters())
    assert [ids(g.transitions) for g in result.groups] == [["t1", "t2"]]
    assert [ids(g.shared_places) for g in result.groups] == [["p1"]]
    assert (result.transitions_in_conflict, result.transitions_without_conflict) == (2, 1)


def test_conflict_is_transitive_through_shared_places():
    chain = net(
        places=["a", "b"],
        transitions=["t1", "t2", "t3"],
        arcs=[("a", "t1"), ("a", "t2"), ("b", "t2"), ("b", "t3")],
    )
    result = conflict_sets(structure=chain, parameters=ConflictSetsParameters())
    assert [ids(g.transitions) for g in result.groups] == [["t1", "t2", "t3"]]


def test_the_confusion_net_has_one_group_and_the_cap_applies():
    assert conflict_sets(structure=CONFUSION, parameters=ConflictSetsParameters()).total == 1
    two = net(
        places=["a", "b"],
        transitions=["t1", "t2", "u1", "u2"],
        arcs=[("a", "t1"), ("a", "t2"), ("b", "u1"), ("b", "u2")],
    )
    capped = conflict_sets(structure=two, parameters=ConflictSetsParameters(max_groups=1))
    assert (len(capped.groups), capped.total) == (1, 2)


# ---- connected components -------------------------------------------------------------------


def test_a_connected_net_is_one_component():
    result = connected_components(structure=MUTEX, parameters=ConnectedComponentsParameters())
    assert result.total == 1
    assert (result.components[0].places, result.components[0].transitions) == (3, 2)


def test_unlinked_parts_are_separate_components_largest_first():
    two = net(
        places=["a", "b", "c"],
        transitions=["t", "u"],
        arcs=[("a", "t"), ("t", "b"), ("c", "u")],
    )
    result = connected_components(structure=two, parameters=ConnectedComponentsParameters())
    assert [ids(c.elements) for c in result.components] == [["a", "b", "t"], ["c", "u"]]


def test_a_big_component_lists_a_prefix_and_says_so():
    result = connected_components(
        structure=MUTEX, parameters=ConnectedComponentsParameters(max_elements=2)
    )
    component = result.components[0]
    assert (len(component.elements), component.truncated) == (2, True)
    assert component.places + component.transitions == 5


def test_an_isolated_element_is_a_component():
    alone = net(places=["a", "b"], transitions=["t"], arcs=[("a", "t")])
    result = connected_components(
        structure=alone, parameters=ConnectedComponentsParameters(max_components=1)
    )
    assert [ids(c.elements) for c in result.components] == [["a", "t"]]
    assert result.total == 2  # b is alone; only the largest is listed
