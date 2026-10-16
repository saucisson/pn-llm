"""Family-level statistics of the evaluation (docs/evaluation.md, procedure 2 to 4).

Families, not instances, are the unit: repetitions and instances are averaged inside a family
first. Two conditions are compared by the paired difference per family, with a percentile
bootstrap interval over families (seeded, so the same data gives the same interval), and the
secondary tests are corrected with Holm's method. A family missing a value for one of the two
conditions is left out of that comparison and counted, never filled in.
"""

from __future__ import annotations

import random

from pydantic import Field

from .experiment import RunRecord
from .models import DomainModel

CONFIDENCE_TAIL = 0.025


class FamilyValue(DomainModel):
    """One measure of one condition on one family, the mean of its repetitions."""

    condition: str
    family: str
    measure: str
    value: float


class MeasuredRun(DomainModel):
    """A measure read from one run, absent when the run could not produce it."""

    measure: str
    value: float | None


def measures_of(*, record: RunRecord) -> tuple[MeasuredRun, ...]:
    """Read the measures of the protocol that one run gives (M4 to M6, and the decided share)."""
    decided = [p for p in record.properties if p.verdict.value in {"TRUE", "FALSE"}]
    return (
        MeasuredRun(
            measure="M3_decided",
            value=len(decided) / len(record.properties) if record.properties else None,
        ),
        MeasuredRun(measure="M4_non_trivial", value=record.non_triviality.share),
        MeasuredRun(measure="M5_mutation_score", value=record.mutation.score),
        MeasuredRun(measure="M6_fault_finding", value=record.mutation.fault_finding),
    )


def family_values(*, records: tuple[RunRecord, ...]) -> tuple[FamilyValue, ...]:
    """Average each measure over the runs of a condition on a family."""
    pooled: dict[tuple[str, str, str], list[float]] = {}
    for record in records:
        for item in measures_of(record=record):
            if item.value is not None:
                key = (record.spec.condition, record.spec.family, item.measure)
                pooled.setdefault(key, []).append(item.value)
    return tuple(
        FamilyValue(condition=c, family=f, measure=m, value=sum(v) / len(v))
        for (c, f, m), v in sorted(pooled.items())
    )


class PairedComparison(DomainModel):
    """The difference of a measure between two conditions, paired by family."""

    measure: str
    condition: str
    baseline: str
    families: int
    excluded: tuple[str, ...]
    mean_difference: float | None
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    adjusted_p_value: float | None = None
    # The interval leaves zero out: the sign of the difference is established over the families.
    excludes_zero: bool = False
    per_family: tuple[FamilyValue, ...] = Field(default=(), description="the paired differences")


def compare(
    *,
    values: tuple[FamilyValue, ...],
    condition: str,
    baseline: str,
    measure: str,
    seed: str,
    resamples: int = 10_000,
) -> PairedComparison:
    """Compare two conditions on a measure over the families that have both."""
    mine = {v.family: v.value for v in values if v.condition == condition and v.measure == measure}
    other = {v.family: v.value for v in values if v.condition == baseline and v.measure == measure}
    both = sorted(mine.keys() & other.keys())
    excluded = tuple(sorted((mine.keys() | other.keys()) - set(both)))
    differences = [mine[f] - other[f] for f in both]
    per_family = tuple(
        FamilyValue(condition=f"{condition}-{baseline}", family=f, measure=measure, value=d)
        for f, d in zip(both, differences, strict=True)
    )
    if not differences:
        return PairedComparison(
            measure=measure,
            condition=condition,
            baseline=baseline,
            families=0,
            excluded=excluded,
            mean_difference=None,
            ci_low=None,
            ci_high=None,
            p_value=None,
        )
    rng = random.Random(f"{seed}/{condition}/{baseline}/{measure}")  # noqa: S311 - reproducible
    n = len(differences)
    means = sorted(sum(rng.choices(differences, k=n)) / n for _ in range(resamples))
    low = means[int(CONFIDENCE_TAIL * resamples)]
    high = means[min(resamples - 1, int((1 - CONFIDENCE_TAIL) * resamples))]
    at_most_zero = sum(m <= 0 for m in means) / resamples
    at_least_zero = sum(m >= 0 for m in means) / resamples
    p_value = min(1.0, max(2 * min(at_most_zero, at_least_zero), 1 / (resamples + 1)))
    return PairedComparison(
        measure=measure,
        condition=condition,
        baseline=baseline,
        families=n,
        excluded=excluded,
        mean_difference=sum(differences) / n,
        ci_low=low,
        ci_high=high,
        p_value=p_value,
        excludes_zero=low > 0 or high < 0,
        per_family=per_family,
    )


def holm(*, comparisons: tuple[PairedComparison, ...]) -> tuple[PairedComparison, ...]:
    """Adjust the p-values of the comparisons with Holm's step-down method, keeping their order."""
    testable = sorted(
        (i for i, c in enumerate(comparisons) if c.p_value is not None),
        key=lambda i: comparisons[i].p_value or 0.0,
    )
    adjusted: dict[int, float] = {}
    running = 0.0
    for rank, index in enumerate(testable):
        p_value = comparisons[index].p_value or 0.0
        running = max(running, min(1.0, (len(testable) - rank) * p_value))
        adjusted[index] = running
    return tuple(
        c.model_copy(update={"adjusted_p_value": adjusted.get(i)})
        for i, c in enumerate(comparisons)
    )


class EvaluationAnalysis(DomainModel):
    """The analysis of a set of runs: the primary outcome, the corrected secondaries, the table."""

    primary: PairedComparison
    secondary: tuple[PairedComparison, ...]
    families: tuple[FamilyValue, ...]


# C4 of the protocol: L3 against L2 against L1, N against L2; plus the other measures of L3 and B0.
SECONDARY_PAIRS = (("L3", "L2"), ("L2", "L1"), ("N", "L2"), ("L3", "B0"))
SECONDARY_MEASURES = ("M3_decided", "M4_non_trivial", "M5_mutation_score", "M6_fault_finding")


def analyze_runs(*, records: tuple[RunRecord, ...], seed: str) -> EvaluationAnalysis:
    """Run the protocol's analysis: primary L3 against B0 on M6, Holm-corrected secondaries."""
    values = family_values(records=records)
    primary = compare(
        values=values, condition="L3", baseline="B0", measure="M6_fault_finding", seed=seed
    )
    secondary = holm(
        comparisons=tuple(
            compare(values=values, condition=a, baseline=b, measure=m, seed=seed)
            for a, b in SECONDARY_PAIRS
            for m in SECONDARY_MEASURES
            if not (a == "L3" and b == "B0" and m == "M6_fault_finding")
        )
    )
    return EvaluationAnalysis(primary=primary, secondary=secondary, families=values)
