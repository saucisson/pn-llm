import pytest

from app.application.checks import CheckService
from app.application.nets import NetService
from app.application.selection import SelectionService
from app.domain.formula_text import formula_from_text
from app.domain.models import CheckRequest, JobState, Verdict
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from app.infrastructure.sqlite_results import SqliteResults
from tests.support import LEASE, PortfolioEngines


def formula(text, formula_id="f", logic="state"):
    return formula_from_text(text=text, formula_id=formula_id, logic=logic, gloss="", origin="user")


@pytest.fixture
def net_id(store, mutex_pnml):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    return nets.register(payload=mutex_pnml, format=NetFormat.PNML).stored.summary.net_id


def service(*, store, settings, answers):
    engines = PortfolioEngines(answers=answers)
    checks = CheckService(
        nets=store,
        jobs=store,
        engines=engines,
        lease_seconds=LEASE,
        selection=SelectionService(
            nets=store, engines=engines, results=SqliteResults(path=settings.database_path)
        ),
    )
    return checks, engines


def run(checks, net_id, *formulas, **options):
    request = CheckRequest(
        formulas=formulas or (formula('"crit1" >= 1'),), engine="auto", **options
    )
    job = checks.submit(net_id=net_id, request=request).job
    checks.drain()
    return checks.get(job_id=job.job_id)


def test_engines_that_agree_give_one_result_from_the_fastest_with_both_as_evidence(
    store, settings, net_id
):
    checks, engines = service(
        store=store,
        settings=settings,
        answers={"tapaal": ("TRUE", 3.0, None, False), "itstools": ("TRUE", 1.0, None, False)},
    )
    job = run(checks, net_id, portfolio=2, cross_check=True)
    (result,) = job.results
    assert job.state is JobState.DONE
    assert (result.verdict, result.engine, result.agreement) == (Verdict.TRUE, "itstools", "agree")
    assert sorted(a.engine for a in result.alternatives) == ["itstools", "tapaal"]
    assert {run[1] for run in engines.runs} == {f"{job.job_id}.itstools", f"{job.job_id}.tapaal"}


def test_the_first_definitive_answer_stops_the_engines_still_running(store, settings, net_id):
    checks, engines = service(
        store=store,
        settings=settings,
        answers={"itstools": ("TRUE", 1.0, None, False), "tapaal": ("TRUE", 9.0, None, True)},
    )
    job = run(checks, net_id, portfolio=2)
    (result,) = job.results
    assert (result.verdict, result.engine, result.agreement) == (Verdict.TRUE, "itstools", "single")
    assert f"{job.job_id}.tapaal" in engines.stopped


def test_a_cross_check_waits_for_every_engine(store, settings, net_id):
    checks, engines = service(
        store=store,
        settings=settings,
        answers={"itstools": ("TRUE", 1.0, None, False), "tapaal": ("TRUE", 9.0, None, False)},
    )
    job = run(checks, net_id, portfolio=2, cross_check=True)
    assert engines.stopped == []
    assert job.results[0].agreement == "agree"


def test_contradicting_verdicts_are_reported_as_such_and_never_resolved(store, settings, net_id):
    checks, _ = service(
        store=store,
        settings=settings,
        answers={"itstools": ("TRUE", 1.0, None, False), "tapaal": ("FALSE", 2.0, None, False)},
    )
    job = run(checks, net_id, portfolio=2, cross_check=True)
    (result,) = job.results
    assert result.verdict is Verdict.UNKNOWN
    assert result.agreement == "contradiction"
    assert "engines_contradict" in result.warnings
    assert {(a.engine, a.verdict) for a in result.alternatives} == {
        ("itstools", Verdict.TRUE),
        ("tapaal", Verdict.FALSE),
    }
    assert result.arbitration is None
    assert result.trace_url is None


def test_a_counterexample_the_net_confirms_settles_a_contradiction_about_an_invariant(
    store, settings, net_id
):
    # AG crit1 < 1 is false: enter1 puts a token in crit1. One engine says so with that trace.
    invariant = formula('AG "crit1" < 1', logic="ctl")
    checks, _ = service(
        store=store,
        settings=settings,
        answers={
            "itstools": ("TRUE", 1.0, None, False),
            "tapaal": ("FALSE", 2.0, ("enter1",), False),
        },
    )
    job = run(checks, net_id, invariant, portfolio=2, cross_check=True)
    (result,) = job.results
    assert (result.verdict, result.agreement, result.arbitration) == (
        Verdict.FALSE,
        "contradiction",
        "counterexample_replayed",
    )
    assert result.engine == "tapaal"
    assert result.trace_url == f"/v1/jobs/{job.job_id}/results/0/trace"
    assert "engines_contradict" in result.warnings


def test_a_counterexample_that_does_not_violate_the_invariant_settles_nothing(
    store, settings, net_id
):
    invariant = formula('AG "crit1" < 1', logic="ctl")
    checks, _ = service(
        store=store,
        settings=settings,
        answers={
            "itstools": ("TRUE", 1.0, None, False),
            "tapaal": ("FALSE", 2.0, ("enter1", "leave1"), False),
        },
    )
    result = run(checks, net_id, invariant, portfolio=2, cross_check=True).results[0]
    assert (result.verdict, result.agreement, result.arbitration) == (
        Verdict.UNKNOWN,
        "contradiction",
        None,
    )


def test_a_formula_the_engines_cannot_settle_is_left_to_the_one_that_answered(
    store, settings, net_id
):
    checks, _ = service(
        store=store,
        settings=settings,
        answers={"itstools": ("UNKNOWN", 1.0, None, False), "tapaal": ("FALSE", 2.0, None, False)},
    )
    result = run(checks, net_id, portfolio=2, cross_check=True).results[0]
    assert (result.verdict, result.engine, result.agreement) == (Verdict.FALSE, "tapaal", "single")


def test_without_a_portfolio_one_engine_runs_and_no_evidence_list_is_added(store, settings, net_id):
    checks, engines = service(
        store=store,
        settings=settings,
        answers={"itstools": ("TRUE", 1.0, None, False), "tapaal": ("TRUE", 2.0, None, False)},
    )
    job = run(checks, net_id)
    result = job.results[0]
    assert (result.engine, result.agreement, result.alternatives) == ("itstools", "single", ())
    assert [r[1] for r in engines.runs] == [job.job_id]


def test_the_reduce_option_reaches_the_engines(store, settings, net_id):
    checks, engines = service(
        store=store, settings=settings, answers={"itstools": ("TRUE", 1.0, None, False)}
    )
    run(checks, net_id, reduce=False)
    assert [r[2] for r in engines.runs] == [False]


def test_a_portfolio_needs_engine_auto():
    with pytest.raises(ValueError, match="engine auto"):
        CheckRequest(formulas=(formula('"crit1" >= 1'),), engine="tapaal", portfolio=2)
