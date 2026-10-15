import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain.formula import Formula
from app.domain.models import Verdict as VerdictValue
from app.domain.sessions import (
    Answer,
    AssistantMessage,
    BudgetExhausted,
    CheckSubmitted,
    DescriptionAccepted,
    DescriptionProposed,
    PropertyProposed,
    Question,
    RunFinished,
    SessionCancelled,
    SessionError,
    SessionEvent,
    SessionStarted,
    StoredEvent,
    ToolCall,
    ToolResult,
    UserMessage,
    Verdict,
)

FORMULA = Formula.model_validate(
    {"id": "f1", "logic": "state", "ast": {"op": "deadlock"}, "gloss": "can it block?"}
)

EVENTS = [
    SessionStarted(net_id="n", description_id="d", description_origin="user", goal="is it safe?"),
    UserMessage(text="hello"),
    AssistantMessage(text="I will look at the net."),
    ToolCall(call_id="c1", tool="net_places", arguments='{"limit": 5}'),
    ToolResult(call_id="c1", tool="net_places", ok=True, content='{"data": []}'),
    PropertyProposed(formula=FORMULA, rationale="a deadlock would be a bug"),
    CheckSubmitted(job_id="j1", formula_ids=("f1",)),
    Verdict(
        job_id="j1",
        result_index=0,
        formula_id="f1",
        verdict=VerdictValue.FALSE,
        engine="itstools",
        engine_version="3.2",
        has_trace=True,
    ),
    Question(question_id="q1", text="Which resource is shared?"),
    Answer(question_id="q1", text="the lock"),
    BudgetExhausted(budget="steps"),
    SessionError(code="llm_unavailable", message="no key"),
    RunFinished(reason="completed"),
    DescriptionProposed(proposal_id="p1", text="A lock shared by two processes."),
    DescriptionAccepted(proposal_id="p1", description_id="d1"),
    SessionCancelled(),
]
ADAPTER: TypeAdapter[SessionEvent] = TypeAdapter(SessionEvent)


@pytest.mark.parametrize("event", EVENTS, ids=lambda event: event.kind)
def test_every_event_kind_round_trips_through_json(event):
    assert ADAPTER.validate_json(ADAPTER.dump_json(event)) == event


def test_the_vocabulary_is_version_one_plus_the_description_kinds():
    assert [event.kind for event in EVENTS] == [
        "session_started",
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "property_proposed",
        "check_submitted",
        "verdict",
        "question",
        "answer",
        "budget_exhausted",
        "session_error",
        "run_finished",
        "description_proposed",
        "description_accepted",
        "session_cancelled",
    ]


def test_an_event_of_an_unknown_kind_is_refused():
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"kind": "verdict_by_llm", "text": "FALSE"})


@pytest.mark.parametrize(
    "missing",
    ["job_id", "formula_id", "engine", "engine_version", "verdict", "result_index"],
)
def test_a_verdict_cannot_be_built_without_its_engine_result(missing):
    fields = {
        "job_id": "j1",
        "result_index": 0,
        "formula_id": "f1",
        "verdict": "TRUE",
        "engine": "itstools",
        "engine_version": "3.2",
    }
    del fields[missing]
    with pytest.raises(ValidationError):
        Verdict(**fields)


@pytest.mark.parametrize("field", ["job_id", "formula_id", "engine", "engine_version"])
def test_a_verdict_cannot_have_an_empty_reference(field):
    fields = {
        "job_id": "j1",
        "result_index": 0,
        "formula_id": "f1",
        "verdict": "TRUE",
        "engine": "itstools",
        "engine_version": "3.2",
        field: "",
    }
    with pytest.raises(ValidationError):
        Verdict(**fields)


def test_assistant_text_is_labelled_as_written_by_the_llm():
    assert AssistantMessage(text="TRUE, I checked").source == "llm"
    with pytest.raises(ValidationError):
        AssistantMessage(text="x", source="engine")


def test_event_numbers_start_at_one():
    with pytest.raises(ValidationError):
        StoredEvent(session_id="s", number=0, at=1.0, event=EVENTS[1])


def test_a_goal_and_a_user_message_cannot_be_empty():
    with pytest.raises(ValidationError):
        SessionStarted(net_id="n", goal="")
    with pytest.raises(ValidationError):
        UserMessage(text="")
