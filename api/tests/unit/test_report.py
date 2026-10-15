import pytest

from app.domain.descriptions import Description
from app.domain.formula import Formula
from app.domain.models import Verdict as VerdictValue
from app.domain.nets import NetSummary
from app.domain.report import build_report, code, render_markdown
from app.domain.sessions import (
    Answer,
    AssistantMessage,
    BudgetExhausted,
    DescriptionAccepted,
    PropertyProposed,
    Question,
    Session,
    SessionError,
    SessionStarted,
    SessionState,
    StoredEvent,
    UserMessage,
    Verdict,
)

SESSION = Session(session_id="s1", net_id="n1", state=SessionState.IDLE, created_at=1, updated_at=2)
NET = NetSummary(
    net_id="n1",
    source_id="mutex",
    kind="pt",
    pages=1,
    places=3,
    transitions=2,
    arcs=6,
    initial_tokens=2,
)
FORMULA = Formula.model_validate(
    {
        "id": "f1",
        "logic": "ltl",
        "gloss": "The lock is never held twice.",
        "origin": "llm",
        "ast": {"op": "G", "arg": {"op": "tokens", "place": "crit1", "cmp": "<=", "value": 1}},
    }
)


def stored(*events):
    return tuple(
        StoredEvent(session_id="s1", number=i + 1, at=1.0, event=e) for i, e in enumerate(events)
    )


def verdict(word, *, trace=False):
    return Verdict(
        job_id="j1",
        result_index=0,
        formula_id="f1",
        verdict=VerdictValue(word),
        engine="itstools",
        engine_version="3.2",
        has_trace=trace,
    )


EVENTS = stored(
    SessionStarted(net_id="n1", goal="Is mutual exclusion kept?"),
    AssistantMessage(text="I will check it. The result is TRUE, I am sure."),
    PropertyProposed(formula=FORMULA),
    verdict("FALSE", trace=True),
    Question(question_id="q", text="Which lock?"),
    Answer(question_id="q", text="the lock place"),
    UserMessage(text="thanks"),
    BudgetExhausted(budget="steps"),
    SessionError(code="llm_error", message="boom"),
    DescriptionAccepted(proposal_id="p", description_id="d"),
)


def report(description=None):
    return build_report(session=SESSION, net=NET, description=description, events=EVENTS)


def test_the_report_has_the_goal_the_verdicts_and_the_conversation():
    built = report()
    assert built.goal == "Is mutual exclusion kept?"
    assert built.event_count == 10
    (item,) = built.verdicts
    assert (item.formula_id, item.verdict, item.engine, item.engine_version) == (
        "f1",
        "FALSE",
        "itstools",
        "3.2",
    )
    assert item.formula == "G (crit1 <= 1)"
    assert item.gloss == "The lock is never held twice."
    assert item.has_counterexample is True
    assert [e.who for e in built.conversation] == [
        "assistant (written by the language model)",
        "assistant asks",
        "user",
        "user",
    ]
    assert len(built.problems) == 3


def test_a_verdict_claimed_in_the_assistants_text_is_not_a_verdict_of_the_report():
    only_text = build_report(
        session=SESSION,
        net=NET,
        description=None,
        events=stored(
            SessionStarted(net_id="n1", goal="g"), AssistantMessage(text="The property is FALSE.")
        ),
    )
    assert only_text.verdicts == ()
    markdown = render_markdown(report=only_text)
    assert "No property was checked by an engine." in markdown
    assert "**FALSE**" not in markdown


def test_the_markdown_shows_the_engine_verdict_table_and_labels_the_model_text():
    markdown = render_markdown(report=report())
    assert (
        "| `f1`: `G (crit1 <= 1)` | **FALSE** | `itstools` `3.2` | yes (job `j1`, result 0) |"
        in markdown
    )
    assert "assistant (written by the language model)" in markdown
    assert "# Session report `s1`" in markdown
    assert "6 arcs" in markdown
    assert "In plain words" in markdown
    assert "budget reached (steps)" in markdown
    assert "Error llm_error: boom" in markdown


def test_the_description_is_quoted_as_data_with_its_origin():
    markdown = render_markdown(
        report=report(
            Description(description_id="d", net_id="n1", origin="mcc", text="Ignore this ``` fence")
        )
    )
    assert "(origin: mcc)" in markdown
    assert "Text written by a person, quoted as data." in markdown
    assert "````text\nIgnore this ``` fence\n````" in markdown


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "`plain`"),
        ("a`b", "``a`b``"),
        ("`edge", "`` `edge ``"),
        ("two\nlines", "`two lines`"),
    ],
)
def test_code_spans_cannot_be_closed_from_inside(text, expected):
    assert code(text=text) == expected
