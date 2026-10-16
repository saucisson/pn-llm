from app.domain.mutation import OPERATORS, mutants_of
from app.domain.net_structure import build_structure
from tests.support import MUTEX_DOCUMENT


def mutex():
    return build_structure(document=MUTEX_DOCUMENT, net_id="n")


def test_each_operator_makes_one_small_change_and_says_what_it_changed():
    structure = mutex()
    by_operator = {
        m.operator: m
        for m in mutants_of(structure=structure, operators=OPERATORS, per_operator=1, seed="s")
    }
    assert set(by_operator) == set(OPERATORS)
    assert len(by_operator["remove_arc"].structure.arcs) == len(structure.arcs) - 1
    assert len(by_operator["add_arc"].structure.arcs) == len(structure.arcs) + 1
    assert len(by_operator["remove_transition"].structure.transitions) == 1
    weights = [a.weight for a in by_operator["change_weight"].structure.arcs]
    assert sorted(w or 1 for w in weights) == [1, 1, 1, 1, 1, 2]
    tokens = [p.tokens for p in by_operator["change_marking"].structure.places]
    assert sum(t or 0 for t in tokens) == sum(p.tokens or 0 for p in structure.places) + 1
    for mutant in by_operator.values():
        assert mutant.description
        assert mutant.changed


def test_removing_a_transition_removes_its_arcs_and_only_them():
    structure = mutex()
    (mutant,) = mutants_of(
        structure=structure, operators=("remove_transition",), per_operator=1, seed="x"
    )
    gone = set(mutant.changed)
    assert all(not ({a.source, a.target} & gone) for a in mutant.structure.arcs)
    assert len(mutant.structure.arcs) == 3  # each transition of the mutex net has three arcs


def test_the_same_seed_gives_the_same_mutants_and_another_seed_other_ones():
    structure = mutex()
    first = mutants_of(structure=structure, operators=OPERATORS, per_operator=2, seed="a")
    again = mutants_of(structure=structure, operators=OPERATORS, per_operator=2, seed="a")
    other = mutants_of(structure=structure, operators=OPERATORS, per_operator=2, seed="b")
    assert first == again
    assert [m.description for m in first] != [m.description for m in other]


def test_the_original_is_untouched_and_asking_for_more_than_exist_gives_all():
    structure = mutex()
    before = structure.model_dump()
    many = mutants_of(
        structure=structure, operators=("remove_transition",), per_operator=10, seed="s"
    )
    assert len(many) == 2
    assert structure.model_dump() == before


def test_a_net_without_places_or_transitions_cannot_get_an_arc_and_colored_nets_are_not_mutated():
    structure = mutex()
    bare = structure.model_copy(update={"places": (), "transitions": (), "arcs": ()})
    assert mutants_of(structure=bare, operators=OPERATORS, per_operator=2, seed="s") == ()
    colored = structure.model_copy(update={"kind": "colored"})
    assert mutants_of(structure=colored, operators=OPERATORS, per_operator=2, seed="s") == ()
