import pytest

from app.domain.analysis_stats import FamilyValue, compare, family_values, holm


def value(condition, family, number, measure="M6_fault_finding"):
    return FamilyValue(condition=condition, family=family, measure=measure, value=number)


def gain(*, per_family, baseline=0.2):
    values = []
    for i, d in enumerate(per_family):
        values += [value("L3", f"F{i}", baseline + d), value("B0", f"F{i}", baseline)]
    return tuple(values)


def test_a_consistent_gain_over_families_has_an_interval_that_excludes_zero():
    result = compare(
        values=gain(per_family=[0.10, 0.15, 0.12, 0.2, 0.08, 0.11, 0.14, 0.13]),
        condition="L3",
        baseline="B0",
        measure="M6_fault_finding",
        seed="s",
    )
    assert result.families == 8
    assert result.mean_difference == pytest.approx(0.12875)
    assert result.ci_low > 0
    assert result.excludes_zero
    assert result.p_value < 0.01


def test_mixed_differences_give_an_interval_around_zero():
    result = compare(
        values=gain(per_family=[0.2, -0.2, 0.1, -0.1, 0.15, -0.15]),
        condition="L3",
        baseline="B0",
        measure="M6_fault_finding",
        seed="s",
    )
    assert result.ci_low < 0 < result.ci_high
    assert not result.excludes_zero
    assert result.p_value > 0.5


def test_the_same_data_and_seed_give_the_same_interval_another_seed_a_close_one():
    values = gain(per_family=[0.1, 0.3, -0.1, 0.2, 0.05])
    args = {"values": values, "condition": "L3", "baseline": "B0", "measure": "M6_fault_finding"}
    assert compare(seed="a", **args) == compare(seed="a", **args)
    other = compare(seed="b", **args)
    assert abs(compare(seed="a", **args).ci_low - other.ci_low) < 0.1


def test_a_family_missing_for_one_condition_is_excluded_and_named_never_filled_in():
    values = (*gain(per_family=[0.1, 0.1]), value("L3", "Only3", 0.9), value("B0", "OnlyB", 0.1))
    result = compare(
        values=values, condition="L3", baseline="B0", measure="M6_fault_finding", seed="s"
    )
    assert result.families == 2
    assert result.excluded == ("Only3", "OnlyB")


def test_no_common_family_gives_no_estimate():
    result = compare(
        values=(value("L3", "A", 0.5), value("B0", "B", 0.5)),
        condition="L3",
        baseline="B0",
        measure="M6_fault_finding",
        seed="s",
    )
    assert (result.families, result.mean_difference, result.p_value) == (0, None, None)


def test_identical_conditions_have_a_p_value_of_one():
    result = compare(
        values=gain(per_family=[0.0, 0.0, 0.0]),
        condition="L3",
        baseline="B0",
        measure="M6_fault_finding",
        seed="s",
    )
    assert result.p_value == 1.0
    assert not result.excludes_zero


def test_holm_scales_the_smallest_p_by_the_number_of_tests_and_keeps_order_monotone():
    def one(p):
        return compare(
            values=gain(per_family=[0.1, 0.2]),
            condition="L3",
            baseline="B0",
            measure="M6_fault_finding",
            seed="s",
        ).model_copy(update={"p_value": p})

    adjusted = holm(comparisons=(one(0.04), one(0.01), one(0.03), one(None)))
    assert [round(c.adjusted_p_value, 3) if c.adjusted_p_value else None for c in adjusted] == [
        0.06,
        0.03,
        0.06,
        None,
    ]
    assert holm(comparisons=()) == ()


def test_runs_are_averaged_within_a_family_before_comparing(store):
    from app.domain.analysis_stats import measures_of
    from app.domain.nets import NetFormat
    from tests.support import MUTEX_PNML
    from tests.unit.test_experiment import ArcCounting, runner_over, spec

    nets, runner = runner_over(store=store, engines=ArcCounting(trace_steps=("enter1",)))
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    first = runner.run_baseline(spec=spec(properties=6), net_id=net_id)
    second = runner.run_baseline(
        spec=spec(properties=6).model_copy(update={"repetition": 1, "seed": "s2"}), net_id=net_id
    )
    by_measure = {m.measure: m.value for m in measures_of(record=first)}
    assert set(by_measure) == {
        "M3_decided",
        "M4_non_trivial",
        "M5_mutation_score",
        "M6_fault_finding",
    }
    assert by_measure["M3_decided"] == 1.0
    averaged = {v.measure: v.value for v in family_values(records=(first, second))}
    one = {m.measure: m.value for m in measures_of(record=second)}
    assert averaged["M6_fault_finding"] == pytest.approx(
        (by_measure["M6_fault_finding"] + one["M6_fault_finding"]) / 2
    )
    assert {v.family for v in family_values(records=(first, second))} == {"Mutex"}


def test_the_analysis_has_a_primary_outcome_and_corrected_secondaries():
    from app.domain.analysis_stats import analyze_runs

    analysis = analyze_runs(records=(), seed="s")
    assert (analysis.primary.condition, analysis.primary.baseline) == ("L3", "B0")
    assert analysis.primary.families == 0
    assert analysis.families == ()
    pairs = {(c.condition, c.baseline, c.measure) for c in analysis.secondary}
    assert ("L3", "L2", "M6_fault_finding") in pairs
    assert ("N", "L2", "M5_mutation_score") in pairs
    assert ("L3", "B0", "M6_fault_finding") not in pairs  # that one is the primary
    assert len(analysis.secondary) == 15
