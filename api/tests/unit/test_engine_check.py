import pytest
from pydantic import ValidationError

from app.domain.engine_check import all_error, initial_marking_of, interpret_report
from app.domain.engine_contract import (
    EngineFormulaResult,
    EngineReport,
    EngineRequest,
    EngineTrace,
    EngineTraceStep,
    ReportedResult,
)
from app.domain.models import Verdict
from app.domain.net_structure import build_structure
from tests.support import MUTEX_DOCUMENT, make_formula, make_request

STRUCTURE = build_structure(document=MUTEX_DOCUMENT, net_id="n")
REQUEST = make_request(
    formulas=[make_formula(formula_id="f1"), make_formula(formula_id="f2")], engine="x"
)


def reported(*, formula_id, verdict="TRUE", steps=None, loop_start=None):
    trace = (
        None
        if steps is None
        else EngineTrace(
            steps=tuple(EngineTraceStep(transition=t) for t in steps), loop_start=loop_start
        )
    )
    return ReportedResult(
        result=EngineFormulaResult(id=formula_id, verdict=Verdict(verdict), time_s=1.0), trace=trace
    )


def report(*results, version="1.0", status="ok", error_code=None):
    return EngineReport(
        tool_name="x", tool_version=version, status=status, error_code=error_code, results=results
    )


def interpret(rep):
    return interpret_report(
        report=rep, request=REQUEST, engine="x", net_id="n", structure=STRUCTURE
    )


def test_a_complete_output_becomes_results_with_the_tool_version():
    outcome = interpret(
        report(reported(formula_id="f1"), reported(formula_id="f2", verdict="FALSE"))
    )
    assert [(r.id, r.verdict, r.engine_version) for r in outcome.results] == [
        ("f1", Verdict.TRUE, "1.0"),
        ("f2", Verdict.FALSE, "1.0"),
    ]
    assert outcome.traces == ()


def test_traces_are_reported_on_the_net_with_names_and_the_initial_marking():
    outcome = interpret(
        report(
            reported(formula_id="f1", verdict="FALSE", steps=["enter1", "leave1"], loop_start=1),
            reported(formula_id="f2"),
        )
    )
    (trace,) = outcome.traces
    assert trace.formula_id == "f1"
    assert [(s.transition.id, s.transition.name) for s in trace.steps] == [
        ("enter1", "enter1"),
        ("leave1", "leave1"),
    ]
    assert trace.loop_start == 1
    assert {(e.place.id, e.tokens) for e in trace.initial_marking.entries} == {
        ("idle1", 1),
        ("lock", 1),
    }


@pytest.mark.parametrize(
    ("results", "reason"),
    [
        ((reported(formula_id="zzz"),), "unknown formula"),
        ((reported(formula_id="f1"), reported(formula_id="f1")), "two results"),
        ((reported(formula_id="f1", steps=["nope"]),), "not a transition"),
        ((reported(formula_id="f1", steps=["crit1"]),), "not a transition"),
        ((reported(formula_id="f1", steps=["enter1"], loop_start=1),), "loop"),
    ],
)
def test_an_inconsistent_output_makes_every_formula_an_error_never_a_verdict(results, reason):
    outcome = interpret(report(*results))
    assert [r.verdict for r in outcome.results] == [Verdict.ERROR, Verdict.ERROR]
    assert reason in outcome.results[0].warnings[0]
    assert outcome.results[0].warnings[0].startswith("invalid_engine_output")
    assert outcome.traces == ()


def test_an_output_without_the_tool_version_is_refused():
    outcome = interpret(report(reported(formula_id="f1"), version=""))
    assert {r.verdict for r in outcome.results} == {Verdict.ERROR}
    assert "tool version" in outcome.results[0].warnings[0]


def test_a_formula_missing_from_the_output_is_an_error_for_that_formula_only():
    outcome = interpret(report(reported(formula_id="f1")))
    assert [r.verdict for r in outcome.results] == [Verdict.TRUE, Verdict.ERROR]
    assert outcome.results[1].warnings == ("missing_in_engine_output",)


def test_a_failed_report_is_an_error_with_its_code():
    outcome = interpret(report(status="failed", error_code="unsupported_net", version=None))
    assert {r.verdict for r in outcome.results} == {Verdict.ERROR}
    assert outcome.results[0].warnings == ("engine_failed: unsupported_net",)


def test_a_partial_report_marks_its_results():
    outcome = interpret(report(reported(formula_id="f1"), status="partial"))
    assert "engine_partial" in outcome.results[0].warnings


def test_non_answers_are_never_verdicts():
    outcome = all_error(request=REQUEST, engine="x", warning="boom")
    assert {r.verdict for r in outcome.results} == {Verdict.ERROR}


def test_initial_marking_of_a_pt_net():
    marking = initial_marking_of(structure=STRUCTURE)
    assert [e.place.id for e in marking.entries] == ["idle1", "lock"]


def test_an_engine_request_needs_its_fields():
    check = make_request()
    EngineRequest(net_id="n", formulas=check.formulas)
    EngineRequest(net_id="n", kind="analysis", operation="p-invariants")
    with pytest.raises(ValidationError):
        EngineRequest(net_id="n")
    with pytest.raises(ValidationError):
        EngineRequest(net_id="n", kind="reduction", operation=None)
