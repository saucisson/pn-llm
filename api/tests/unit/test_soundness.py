import json

import pytest

from app.application.soundness import SoundnessAuditor
from app.domain.models import (
    CheckRequest,
    EngineAnswer,
    FormulaResult,
    Job,
    JobState,
)
from app.domain.models import (
    Verdict as Value,
)
from app.domain.sessions import StoredEvent, Verdict
from app.domain.soundness import audit_session, merge_reports
from tests.support import MUTEX_DOCUMENT, ScriptedEngines, make_formula
from tests.unit.test_tools import build, check, context_for, payload, save


def job_with(*results, state=JobState.DONE):
    request = CheckRequest.model_validate(
        {"formulas": [make_formula(formula_id="f1")], "engine": "x"}
    )
    return Job(job_id="j1", net_id="n", state=state, request=request, results=results)


def result(verdict=Value.FALSE, **extra):
    fields = {"id": "f1", "verdict": verdict, "engine": "itstools", "engine_version": "3.2"}
    return FormulaResult(**{**fields, **extra})


def event(**extra):
    fields = {
        "job_id": "j1",
        "result_index": 0,
        "formula_id": "f1",
        "verdict": Value.FALSE,
        "engine": "itstools",
        "engine_version": "3.2",
        "has_trace": False,
    }
    return StoredEvent(session_id="s", number=7, at=1.0, event=Verdict(**{**fields, **extra}))


def kinds(*, events, jobs):
    return [f.kind for f in audit_session(session_id="s", events=events, jobs=jobs).findings]


def test_a_verdict_that_stands_on_its_result_passes():
    report = audit_session(session_id="s", events=(event(),), jobs=(job_with(result()),))
    assert report.sound
    assert report.verdict_events == 1


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ({"verdict": Value.TRUE}, "verdict_differs_from_result"),
        ({"formula_id": "other"}, "formula_differs_from_result"),
        ({"engine": "tapaal"}, "engine_differs_from_result"),
        ({"engine_version": "9"}, "version_not_recorded"),
        ({"has_trace": True}, "trace_flag_differs_from_result"),
    ],
)
def test_each_way_a_log_can_depart_from_the_engine_result_is_a_finding(changed, expected):
    assert kinds(events=(event(**changed),), jobs=(job_with(result()),)) == [expected]


def test_a_non_answer_turned_into_a_verdict_is_caught():
    unknown = job_with(result(Value.UNKNOWN))
    assert kinds(events=(event(verdict=Value.FALSE),), jobs=(unknown,)) == [
        "verdict_differs_from_result"
    ]
    assert kinds(events=(event(verdict=Value.UNKNOWN),), jobs=(unknown,)) == []


def test_missing_or_unfinished_support_is_a_finding():
    assert kinds(events=(event(),), jobs=()) == ["job_not_found"]
    assert kinds(events=(event(),), jobs=(job_with(state=JobState.QUEUED),)) == ["job_not_finished"]
    assert kinds(events=(event(result_index=3),), jobs=(job_with(result()),)) == [
        "result_not_found"
    ]
    assert kinds(events=(event(),), jobs=(job_with(result(engine_version="unknown")),)) == [
        "version_not_recorded"
    ]


def test_contradictions_between_engines_are_listed_and_not_resolved():
    answers = (
        EngineAnswer(engine="a", verdict=Value.TRUE),
        EngineAnswer(engine="b", verdict=Value.FALSE),
    )
    contradicted = job_with(result(Value.UNKNOWN, agreement="contradiction", alternatives=answers))
    report = audit_session(
        session_id="s", events=(event(verdict=Value.UNKNOWN),), jobs=(contradicted,)
    )
    assert report.sound
    (found,) = report.contradictions
    assert [a.engine for a in found.answers] == ["a", "b"]
    assert merge_reports(reports=(report, report)).verdict_events == 2


def test_a_real_session_log_is_sound_and_a_tampered_one_is_not(store):
    net_id = save(store=store, document=MUTEX_DOCUMENT)
    facade, _ = build(store=store, engines=ScriptedEngines(verdict="FALSE"))
    context = context_for(net_id=net_id)
    outcome = check(facade, context)
    job_id = payload(outcome)["data"]["job_id"]
    store.create_session(session=context.session, started=_started(net_id))
    for e in outcome.events:
        store.append_event(session_id="s1", event=e)
    auditor = SoundnessAuditor(sessions=store, jobs=store)
    assert auditor.audit(session_ids=None).sound
    store.append_event(
        session_id="s1",
        event=Verdict(
            job_id=job_id,
            result_index=0,
            formula_id="reach",
            verdict=Value.TRUE,
            engine="scripted",
            engine_version="1.2.3",
        ),
    )
    report = auditor.audit(session_ids=("s1",))
    assert [f.kind for f in report.findings] == [
        "verdict_differs_from_result",
        "trace_flag_differs_from_result",
    ]
    assert json.loads(report.model_dump_json())["sound"] is False


def _started(net_id):
    from app.domain.sessions import SessionStarted

    return SessionStarted(net_id=net_id, goal="g")
