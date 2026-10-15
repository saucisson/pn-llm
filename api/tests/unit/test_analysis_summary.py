from app.domain.analyses.conflict_sets import ConflictSet, ConflictSetsResult
from app.domain.analyses.connected_components import Component, ConnectedComponentsResult
from app.domain.analyses.dead_transitions import DeadTransitionsResult
from app.domain.analyses.invariants import WeightedElement
from app.domain.analyses.net_class import NetClassResult
from app.domain.analyses.p_invariants import PInvariant, PInvariantsResult
from app.domain.analyses.place_bounds import PlaceBound, PlaceBoundsResult
from app.domain.analyses.t_invariants import TInvariant, TInvariantsResult
from app.domain.analysis_summary import AnalysisResults, Unavailable, summarize_analyses
from app.domain.contract import ElementRef, FiniteBound, UnboundedBound, UnknownBound


def place(index, *, name=True):
    return ElementRef(id=f"p{index}", name=f"place {index}" if name else None, kind="place")


def transition(index):
    return ElementRef(id=f"t{index}", name=f"transition {index}", kind="transition")


def size(summary):
    return len(summary.model_dump_json(exclude_none=True))


def test_small_results_are_summarized_with_names_weights_and_constants():
    results = AnalysisResults(
        net_class=NetClassResult(
            ordinary=True,
            state_machine=False,
            marked_graph=True,
            free_choice=True,
            extended_free_choice=True,
            workflow_like=False,
        ),
        p_invariants=PInvariantsResult(
            invariants=(
                PInvariant(
                    elements=(
                        WeightedElement(element=place(1), weight=2),
                        WeightedElement(element=place(2, name=False), weight=1),
                    ),
                    constant=3,
                ),
            ),
            total=1,
            complete=True,
            uncovered_places=(place(9),),
        ),
        place_bounds=PlaceBoundsResult(
            bounds=(
                PlaceBound(place=place(1), bound=FiniteBound(value=3)),
                PlaceBound(place=place(2), bound=UnboundedBound()),
                PlaceBound(place=place(3), bound=UnknownBound()),
            ),
            total=3,
            finite=1,
            unbounded=1,
            unknown=1,
            largest_finite_bound=3,
            complete=True,
        ),
        dead_transitions=DeadTransitionsResult(
            dead_transitions=(transition(1),), never_marked_places=()
        ),
        unavailable=(Unavailable(operation="minimal-siphons", reason="timeout"),),
    )
    summary = summarize_analyses(results=results, max_chars=4000)
    assert summary.net_class == ("ordinary", "marked graph", "free choice", "extended free choice")
    assert summary.place_invariants.examples == ("2*place 1 + p2 = 3",)
    assert summary.places_in_no_invariant == 1
    assert summary.bounds.largest_finite_bound == 3
    assert summary.dead_transitions.examples == ("transition 1",)
    assert summary.unavailable[0].reason == "timeout"
    assert summary.transition_invariants is None  # not computed: absent, not zero


def test_a_net_of_a_hundred_thousand_places_fits_the_budget_with_exact_counts():
    big = 100_000
    results = AnalysisResults(
        p_invariants=PInvariantsResult(
            invariants=tuple(
                PInvariant(
                    elements=tuple(WeightedElement(element=place(i), weight=1) for i in range(big)),
                    constant=1,
                )
                for _ in range(3)
            ),
            total=250,
            complete=False,
            uncovered_places=tuple(place(i) for i in range(big)),
        ),
        t_invariants=TInvariantsResult(
            invariants=(
                TInvariant(
                    elements=tuple(
                        WeightedElement(element=transition(i), weight=1) for i in range(big)
                    )
                ),
            ),
            total=1,
            complete=True,
            uncovered_transitions=tuple(transition(i) for i in range(big)),
        ),
        dead_transitions=DeadTransitionsResult(
            dead_transitions=tuple(transition(i) for i in range(big)), never_marked_places=()
        ),
        conflict_sets=ConflictSetsResult(
            groups=tuple(
                ConflictSet(transitions=tuple(transition(i) for i in range(big)), shared_places=())
                for _ in range(5)
            ),
            total=5,
            transitions_in_conflict=5 * big,
            transitions_without_conflict=0,
        ),
        connected_components=ConnectedComponentsResult(
            components=tuple(
                Component(places=big, transitions=big, elements=(), truncated=True)
                for _ in range(50)
            ),
            total=50_000,
        ),
    )
    summary = summarize_analyses(results=results, max_chars=2000)
    assert size(summary) <= 2000
    assert summary.place_invariants.count == 250
    assert summary.place_invariants.complete is False
    assert summary.places_in_no_invariant == big
    assert summary.dead_transitions.count == big
    assert summary.components.count == 50_000


def test_examples_shrink_before_anything_else_and_a_loose_budget_keeps_them():
    results = AnalysisResults(
        dead_transitions=DeadTransitionsResult(
            dead_transitions=tuple(transition(i) for i in range(50)), never_marked_places=()
        )
    )
    loose = summarize_analyses(results=results, max_chars=10_000)
    tight = summarize_analyses(results=results, max_chars=130)
    assert len(loose.dead_transitions.examples) == 8
    assert len(tight.dead_transitions.examples) < 8
    assert tight.dead_transitions.count == loose.dead_transitions.count == 50


def test_long_invariants_are_cut_after_a_few_terms_and_conflicts_written_as_alternatives():
    results = AnalysisResults(
        p_invariants=PInvariantsResult(
            invariants=(
                PInvariant(
                    elements=tuple(WeightedElement(element=place(i), weight=1) for i in range(20)),
                    constant=1,
                ),
            ),
            total=1,
            complete=True,
            uncovered_places=(),
        ),
        conflict_sets=ConflictSetsResult(
            groups=(
                ConflictSet(transitions=tuple(transition(i) for i in range(9)), shared_places=()),
            ),
            total=1,
            transitions_in_conflict=9,
            transitions_without_conflict=0,
        ),
        connected_components=ConnectedComponentsResult(
            components=(Component(places=2, transitions=1, elements=(), truncated=False),), total=1
        ),
    )
    summary = summarize_analyses(results=results, max_chars=4000)
    assert summary.place_invariants.examples[0].endswith("+ ... (14 more) = 1")
    assert summary.conflict_groups.examples[0].endswith(" | ...")
    assert summary.components.examples == ("2 places, 1 transitions",)
