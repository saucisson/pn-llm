import pytest

from app.domain.analyses import ANALYSES
from app.domain.analyses.net_class import net_class
from app.domain.analyses.p_invariants import PInvariantsParameters, p_invariants
from app.domain.analyses.semiflows import minimal_semiflows
from app.domain.catalog import find_operation
from app.domain.net_structure import build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.operations import NoParameters, compute_on
from app.domain.pnml_import import import_pnml
from tests.support import MUTEX_PNML

PT = "http://www.pnml.org/version-2009/grammar/ptnet"


def net(*, places, transitions, arcs, marking=None, weights=None):
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


def classes(structure):
    return net_class(structure=structure, parameters=NoParameters())


# A cycle p1 -> t1 -> p2 -> t2 -> p1: both a state machine and a marked graph.
CYCLE = net(
    places=["p1", "p2"],
    transitions=["t1", "t2"],
    arcs=[("p1", "t1"), ("t1", "p2"), ("p2", "t2"), ("t2", "p1")],
    marking={"p1": 1},
)
# A choice: p1 -> t1 | t2, both to p2; and p2 -> t3 -> p1.
CHOICE = net(
    places=["p1", "p2"],
    transitions=["t1", "t2", "t3"],
    arcs=[("p1", "t1"), ("p1", "t2"), ("t1", "p2"), ("t2", "p2"), ("p2", "t3"), ("t3", "p1")],
)
# Fork and join in a loop: not a state machine, a marked graph.
FORK_LOOP = net(
    places=["a", "b", "c", "d"],
    transitions=["f", "j", "back"],
    arcs=[
        ("a", "f"),
        ("f", "b"),
        ("f", "c"),
        ("b", "j"),
        ("c", "j"),
        ("j", "d"),
        ("d", "back"),
        ("back", "a"),
    ],
)
# The same, open: one source place, one sink place, everything on a path between them.
FORK_OPEN = net(
    places=["a", "b", "c", "d"],
    transitions=["f", "j"],
    arcs=[("a", "f"), ("f", "b"), ("f", "c"), ("b", "j"), ("c", "j"), ("j", "d")],
)
# Confusion: t1 needs p1 and p2, t2 needs only p2: extended free choice fails.
CONFUSION = net(
    places=["p1", "p2", "q"],
    transitions=["t1", "t2"],
    arcs=[("p1", "t1"), ("p2", "t1"), ("p2", "t2"), ("t1", "q"), ("t2", "q")],
)
# Two transitions with the same two input places: extended free choice, not free choice.
ASYMMETRIC = net(
    places=["p1", "p2", "q"],
    transitions=["t1", "t2"],
    arcs=[("p1", "t1"), ("p2", "t1"), ("p1", "t2"), ("p2", "t2"), ("t1", "q"), ("t2", "q")],
)


def test_a_cycle_is_a_state_machine_and_a_marked_graph():
    result = classes(CYCLE)
    assert (result.ordinary, result.state_machine, result.marked_graph) == (True, True, True)
    assert result.workflow_like is False  # no source place and no sink place


def test_a_choice_is_a_state_machine_but_not_a_marked_graph():
    result = classes(CHOICE)
    assert (result.state_machine, result.marked_graph) == (True, False)  # p1 has two outputs
    assert (result.free_choice, result.extended_free_choice) == (True, True)


def test_fork_and_join_in_a_loop_is_a_marked_graph_and_not_a_state_machine():
    result = classes(FORK_LOOP)
    assert (result.state_machine, result.marked_graph) == (False, True)
    assert result.workflow_like is False


def test_the_open_fork_and_join_is_workflow_like_and_a_net_with_a_dangling_node_is_not():
    assert classes(FORK_OPEN).workflow_like is True
    dangling = net(
        places=["a", "b", "z"], transitions=["t"], arcs=[("a", "t"), ("t", "b"), ("z", "t")]
    )
    assert classes(dangling).workflow_like is False  # two source places


def test_confusion_is_not_free_choice_in_any_sense():
    result = classes(CONFUSION)
    assert (result.free_choice, result.extended_free_choice) == (False, False)


def test_extended_free_choice_accepts_equal_input_sets_that_free_choice_refuses():
    result = classes(ASYMMETRIC)
    assert result.extended_free_choice is True
    assert result.free_choice is False


def test_a_weighted_arc_removes_every_class_defined_on_ordinary_nets():
    weighted = net(places=["p"], transitions=["t"], arcs=[("p", "t"), ("t", "p")], weights={0: 2})
    result = classes(weighted)
    assert (result.ordinary, result.state_machine, result.marked_graph) == (False, False, False)
    assert result.free_choice is False


def test_mutex_lock_gives_the_two_known_invariants():
    structure = build_structure(
        document=import_pnml(payload=MUTEX_PNML, limits=DocumentLimits()), net_id="n"
    )
    result = p_invariants(structure=structure, parameters=PInvariantsParameters())
    supports = {frozenset(w.element.id for w in inv.elements) for inv in result.invariants}
    assert supports == {frozenset({"crit1", "lock"}), frozenset({"crit1", "idle1"})}
    assert [inv.constant for inv in result.invariants] == [1, 1]
    assert result.complete is True
    assert result.uncovered_places == ()


def test_producer_consumer_has_the_buffer_invariant_with_weights():
    # produce: idle_p -> busy_p; deliver: busy_p -> idle_p + item; consume: item + idle_c -> busy_c;
    # finish: busy_c -> idle_c. Invariants: idle_p + busy_p, idle_c + busy_c.
    structure = net(
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
    result = p_invariants(structure=structure, parameters=PInvariantsParameters())
    supports = {frozenset(w.element.id for w in inv.elements) for inv in result.invariants}
    assert supports == {frozenset({"idle_p", "busy_p"}), frozenset({"idle_c", "busy_c"})}
    assert [p.id for p in result.uncovered_places] == ["item"]


PHILOSOPHERS = net(
    places=["think1", "eat1", "think2", "eat2", "fork1", "fork2"],
    transitions=["take1", "put1", "take2", "put2"],
    arcs=[
        ("think1", "take1"),
        ("fork1", "take1"),
        ("fork2", "take1"),
        ("take1", "eat1"),
        ("eat1", "put1"),
        ("put1", "think1"),
        ("put1", "fork1"),
        ("put1", "fork2"),
        ("think2", "take2"),
        ("fork1", "take2"),
        ("fork2", "take2"),
        ("take2", "eat2"),
        ("eat2", "put2"),
        ("put2", "think2"),
        ("put2", "fork1"),
        ("put2", "fork2"),
    ],
    marking={"think1": 1, "think2": 1, "fork1": 1, "fork2": 1},
)


def test_two_philosophers_conserve_forks_and_states():
    structure = PHILOSOPHERS
    result = p_invariants(structure=structure, parameters=PInvariantsParameters())
    supports = {frozenset(w.element.id for w in inv.elements) for inv in result.invariants}
    assert frozenset({"think1", "eat1"}) in supports
    assert frozenset({"think2", "eat2"}) in supports
    assert frozenset({"fork1", "eat1", "eat2"}) in supports
    assert all(inv.constant >= 1 for inv in result.invariants)


def test_a_weighted_net_gets_weighted_invariants():
    # t consumes 2 from a and produces 1 in b, u does the reverse: a + 2*b... y_a*(-2)+y_b*1=0
    structure = net(
        places=["a", "b"],
        transitions=["t", "u"],
        arcs=[("a", "t"), ("t", "b"), ("b", "u"), ("u", "a")],
        weights={0: 2, 3: 2},
        marking={"a": 2},
    )
    result = p_invariants(structure=structure, parameters=PInvariantsParameters())
    weights = {w.element.id: w.weight for w in result.invariants[0].elements}
    assert weights == {"a": 1, "b": 2}
    assert result.invariants[0].constant == 2


def test_the_search_says_when_it_stopped_at_its_bound_and_lists_at_most_the_cap():
    # 3 independent places -> 3 invariants, one each.
    free = net(places=["a", "b", "c"], transitions=["t"], arcs=[("a", "t"), ("t", "a")])
    capped = p_invariants(structure=free, parameters=PInvariantsParameters(max_invariants=1))
    assert (len(capped.invariants), capped.total) == (1, 3)
    stopped = p_invariants(structure=PHILOSOPHERS, parameters=PInvariantsParameters(max_rows=1))
    assert stopped.complete is False
    assert stopped.invariants == ()


def test_semiflows_of_the_empty_matrix_and_of_a_matrix_without_columns():
    assert minimal_semiflows(matrix=[], max_rows=10).flows == ()
    assert minimal_semiflows(matrix=[[], []], max_rows=10).flows == ((0, 1), (1, 0))


@pytest.mark.parametrize("definition", ANALYSES, ids=lambda d: d.name)
def test_every_analysis_has_distinct_models_and_is_found_by_name(definition):
    assert find_operation(name=definition.name) is definition
    assert definition.parameters_model is not definition.result_model
    assert compute_on(definition=definition, structure=CYCLE, parameters={}) is not None


def test_an_unknown_operation_is_not_found():
    assert find_operation(name="nope") is None
