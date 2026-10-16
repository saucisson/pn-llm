from app.domain.formula import Formula
from app.domain.models import Verdict as Value
from app.domain.sessions import PropertyProposed, Question, StoredEvent, Verdict
from app.domain.study_measures import measure_session

FORMULA = Formula.model_validate(
    {"id": "f", "logic": "state", "ast": {"op": "tokens", "place": "p", "cmp": ">=", "value": 1}}
)


def at(seconds, event, number=1):
    return StoredEvent(session_id="s", number=number, at=100.0 + seconds, event=event)


def verdict(word):
    return Verdict(
        job_id="j",
        result_index=0,
        formula_id="f",
        verdict=Value(word),
        engine="e",
        engine_version="1",
    )


def test_time_to_the_first_definitive_verdict_skips_non_answers():
    events = (
        at(0, Question(question_id="q", text="which?")),
        at(5, PropertyProposed(formula=FORMULA, rationale="r")),
        at(20, verdict("TIMEOUT")),
        at(31.5, verdict("FALSE")),
        at(40, verdict("TRUE")),
    )
    measures = measure_session(session_id="s", events=events)
    assert measures.first_definitive_verdict_s == 31.5
    assert (measures.duration_s, measures.properties, measures.questions) == (40.0, 1, 1)
    assert {(v.verdict, v.count) for v in measures.verdicts} == {
        ("TIMEOUT", 1),
        ("FALSE", 1),
        ("TRUE", 1),
    }


def test_a_session_without_a_definitive_verdict_or_events_has_none():
    only_unknown = measure_session(session_id="s", events=(at(0, verdict("UNKNOWN")),))
    assert only_unknown.first_definitive_verdict_s is None
    empty = measure_session(session_id="s", events=())
    assert (empty.duration_s, empty.properties, empty.verdicts) == (0.0, 0, ())
