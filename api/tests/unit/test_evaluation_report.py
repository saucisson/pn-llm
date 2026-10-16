import json

from app import report_evaluation
from app.domain.analysis_stats import (
    EvaluationAnalysis,
    FamilyValue,
    PairedComparison,
    analyze_runs,
    compare,
)
from app.domain.evaluation_report import claim_outcomes, render_report
from app.domain.soundness import Finding, SoundnessReport


def analysis_with(*, gain, families=8, share=0.9):
    values = []
    for i in range(families):
        values += [
            FamilyValue(
                condition="L3", family=f"F{i}", measure="M6_fault_finding", value=0.2 + gain
            ),
            FamilyValue(condition="B0", family=f"F{i}", measure="M6_fault_finding", value=0.2),
            FamilyValue(condition="L3", family=f"F{i}", measure="M4_non_trivial", value=share),
        ]
    primary = compare(
        values=tuple(values), condition="L3", baseline="B0", measure="M6_fault_finding", seed="s"
    )
    return EvaluationAnalysis(primary=primary, secondary=(), families=tuple(values))


def by_claim(*, analysis, soundness=None):
    return {c.claim.split()[0]: c for c in claim_outcomes(analysis=analysis, soundness=soundness)}


def test_a_gain_below_the_threshold_is_not_met_even_if_significant():
    claims = by_claim(analysis=analysis_with(gain=0.05))
    assert claims["C3"].outcome == "not met"


def test_a_gain_above_the_threshold_with_an_interval_off_zero_is_met():
    # With a constant gain over 8 families the interval is a point above zero.
    assert by_claim(analysis=analysis_with(gain=0.15))["C3"].outcome == "met"


def test_no_common_family_means_not_measured_never_met_or_not_met():
    empty = analyze_runs(records=(), seed="s")
    claims = by_claim(analysis=empty)
    assert claims["C3"].outcome == "not measured"
    assert claims["M4"].outcome == "not measured"
    assert claims["C1"].outcome == "not measured"


def test_one_unsupported_verdict_fails_c1():
    sound = SoundnessReport(sessions=2, verdict_events=10)
    unsound = SoundnessReport(
        sessions=2,
        verdict_events=10,
        findings=(Finding(session_id="s", event_number=3, kind="job_not_found", detail="x"),),
    )
    analysis = analysis_with(gain=0.15)
    assert by_claim(analysis=analysis, soundness=sound)["C1"].outcome == "met"
    assert by_claim(analysis=analysis, soundness=unsound)["C1"].outcome == "not met"


def test_the_non_triviality_threshold_is_eighty_percent():
    assert by_claim(analysis=analysis_with(gain=0.15, share=0.79))["M4"].outcome == "not met"
    assert by_claim(analysis=analysis_with(gain=0.15, share=0.8))["M4"].outcome == "met"


def test_the_report_lists_claims_deviations_exclusions_and_negative_results():
    analysis = analysis_with(gain=0.15)
    comparison = PairedComparison(
        measure="M5_mutation_score",
        condition="L2",
        baseline="L1",
        families=0,
        excluded=("Odd",),
        mean_difference=None,
        ci_low=None,
        ci_high=None,
        p_value=None,
    )
    analysis = analysis.model_copy(update={"secondary": (comparison,)})
    text = render_report(
        analysis=analysis,
        soundness=None,
        deviations=("Family X dropped: engines crash",),
        negative_results="## Learned selection\n- no gain",
    )
    assert "| C3 L3 finds more seeded faults than B0 |" in text
    assert "**met**" in text
    assert "**not measured**" in text
    assert "Family X dropped" in text
    assert "Odd" in text
    assert "no gain" in text
    empty = render_report(
        analysis=analysis_with(gain=0.15), soundness=None, deviations=(), negative_results=""
    )
    assert "None recorded." in empty


def test_the_command_prints_the_report(monkeypatch, capsys, tmp_path):
    analysis = tmp_path / "a.json"
    analysis.write_text(analysis_with(gain=0.15).model_dump_json())
    deviations = tmp_path / "d.txt"
    deviations.write_text("a deviation\n\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--analysis",
            str(analysis),
            "--deviations",
            str(deviations),
            "--negative",
            str(tmp_path / "none"),
        ],
    )
    report_evaluation.report_main()
    out = capsys.readouterr().out
    assert "# Evaluation report" in out
    assert "a deviation" in out
    assert json.loads(analysis.read_text())["primary"]["condition"] == "L3"
