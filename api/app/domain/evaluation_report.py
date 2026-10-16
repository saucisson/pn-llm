"""The report of an evaluation: each claim, its measure, threshold and outcome.

The report is written from the analysis and the soundness audit, never by hand, so a claim cannot
be reported as met when its number does not meet the threshold; a claim whose measure was not made
says so. Deviations from the frozen protocol and the negative results are listed in full.
"""

from __future__ import annotations

from typing import Literal

from .analysis_stats import EvaluationAnalysis
from .models import DomainModel
from .soundness import SoundnessReport

# Provisional thresholds of docs/evaluation.md; the freeze tag records the final ones.
PRIMARY_MIN_GAIN = 0.10
NON_TRIVIAL_MIN = 0.80

Outcome = Literal["met", "not met", "not measured"]


class ClaimOutcome(DomainModel):
    """One claim of the protocol and what the data say of it."""

    claim: str
    measure: str
    threshold: str
    observed: str
    outcome: Outcome


def mean_of(*, analysis: EvaluationAnalysis, condition: str, measure: str) -> float | None:
    """Return the mean over families of a measure under a condition, if any family has it."""
    values = [
        v.value for v in analysis.families if v.condition == condition and v.measure == measure
    ]
    return sum(values) / len(values) if values else None


def claim_outcomes(
    *, analysis: EvaluationAnalysis, soundness: SoundnessReport | None
) -> tuple[ClaimOutcome, ...]:
    """Evaluate the claims that the data decide: C1, C3 and M4 (C2 and M8 need rater data)."""
    claims: list[ClaimOutcome] = []
    if soundness is None:
        claims.append(
            ClaimOutcome(
                claim="C1 no unsupported verdict",
                measure="M1",
                threshold="0 findings",
                observed="audit not run",
                outcome="not measured",
            )
        )
    else:
        claims.append(
            ClaimOutcome(
                claim="C1 no unsupported verdict",
                measure="M1",
                threshold="0 findings",
                observed=(
                    f"{len(soundness.findings)} findings over {soundness.verdict_events} verdicts, "
                    f"{len(soundness.contradictions)} contradictions listed"
                ),
                outcome="met" if soundness.sound else "not met",
            )
        )
    primary = analysis.primary
    if primary.mean_difference is None or primary.ci_low is None or primary.ci_high is None:
        claims.append(
            ClaimOutcome(
                claim="C3 L3 finds more seeded faults than B0",
                measure="M6, L3 minus B0, paired by family",
                threshold=f"at least +{PRIMARY_MIN_GAIN:.2f} with the 95% interval excluding 0",
                observed="no family has both conditions",
                outcome="not measured",
            )
        )
    else:
        met = primary.mean_difference >= PRIMARY_MIN_GAIN and primary.ci_low > 0
        claims.append(
            ClaimOutcome(
                claim="C3 L3 finds more seeded faults than B0",
                measure="M6, L3 minus B0, paired by family",
                threshold=f"at least +{PRIMARY_MIN_GAIN:.2f} with the 95% interval excluding 0",
                observed=(
                    f"{primary.mean_difference:+.3f} over {primary.families} families, "
                    f"95% interval [{primary.ci_low:.3f}, {primary.ci_high:.3f}]"
                ),
                outcome="met" if met else "not met",
            )
        )
    share = mean_of(analysis=analysis, condition="L3", measure="M4_non_trivial")
    claims.append(
        ClaimOutcome(
            claim="M4 L3 properties are non-trivial",
            measure="M4, mean over families",
            threshold=f"at least {NON_TRIVIAL_MIN:.0%}",
            observed="no value" if share is None else f"{share:.1%}",
            outcome="not measured"
            if share is None
            else ("met" if share >= NON_TRIVIAL_MIN else "not met"),
        )
    )
    return tuple(claims)


def render_report(
    *,
    analysis: EvaluationAnalysis,
    soundness: SoundnessReport | None,
    deviations: tuple[str, ...],
    negative_results: str,
) -> str:
    """Write the report as Markdown."""
    lines = ["# Evaluation report", "", "## Claims", ""]
    lines += ["| Claim | Measure | Threshold | Observed | Outcome |", "|---|---|---|---|---|"]
    for claim in claim_outcomes(analysis=analysis, soundness=soundness):
        lines.append(
            f"| {claim.claim} | {claim.measure} | {claim.threshold} | {claim.observed} | "
            f"**{claim.outcome}** |"
        )
    lines += [
        "",
        "C2 (fidelity) and M8 (expert relevance) come from the raters: see `app.rate`.",
        "",
    ]
    lines += ["## Secondary comparisons (Holm-corrected)", ""]
    lines += [
        "| Condition | Against | Measure | Families | Difference | 95% interval | Adjusted p |"
    ]
    lines += ["|---|---|---|---|---|---|---|"]
    for item in analysis.secondary:
        if item.mean_difference is None or item.ci_low is None or item.ci_high is None:
            lines.append(f"| {item.condition} | {item.baseline} | {item.measure} | 0 | - | - | - |")
            continue
        adjusted = "-" if item.adjusted_p_value is None else f"{item.adjusted_p_value:.3f}"
        lines.append(
            f"| {item.condition} | {item.baseline} | {item.measure} | {item.families} | "
            f"{item.mean_difference:+.3f} | [{item.ci_low:.3f}, {item.ci_high:.3f}] | {adjusted} |"
        )
    if analysis.by_provenance:
        lines += ["", "## Primary outcome by provenance of the families", ""]
        lines += ["| Provenance | Families | M6 difference | 95% interval |", "|---|---|---|---|"]
        for label, part in analysis.by_provenance:
            main = part.primary
            if main.mean_difference is None or main.ci_low is None or main.ci_high is None:
                lines.append(f"| {label} | 0 | - | - |")
            else:
                lines.append(
                    f"| {label} | {main.families} | {main.mean_difference:+.3f} | "
                    f"[{main.ci_low:.3f}, {main.ci_high:.3f}] |"
                )
    excluded = sorted({f for c in (analysis.primary, *analysis.secondary) for f in c.excluded})
    lines += ["", "## Families left out of a comparison", ""]
    lines.append(", ".join(excluded) if excluded else "None.")
    lines += ["", "## Deviations from the frozen protocol", ""]
    lines += [f"- {d}" for d in deviations] if deviations else ["None recorded."]
    lines += [
        "",
        "## Negative and null results",
        "",
        negative_results.strip() or "None recorded.",
        "",
    ]
    return "\n".join(lines)
