"""Sessions and their events: a conversation is a persisted, ordered sequence of events (ADR 0008).

The event vocabulary is a public contract (version 1 is frozen): adding a kind is easy, changing
one needs a new ADR. Text written by the LLM is always an ``assistant_message``; a verdict can only
be built from an engine result (ADR 0006), so nothing the model says can look like one.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from .descriptions import DescriptionOrigin
from .formula import Formula
from .models import DomainModel
from .models import Verdict as VerdictValue


class SessionState(StrEnum):
    """Where a session is in its life."""

    QUEUED = "queued"  # a run waits for a worker
    RUNNING = "running"  # a worker is running the agent
    WAITING_FOR_USER = "waiting_for_user"  # a question is open
    IDLE = "idle"  # the agent ended its turn: the user may write again
    CANCELLED = "cancelled"


class Session(DomainModel):
    """A conversation about one net, with an optional description and the goal of the user."""

    session_id: str
    net_id: str
    description_id: str | None = None
    state: SessionState
    created_at: float
    updated_at: float


class SessionStarted(DomainModel):
    """The inputs of the user: the net, an optional description and the goal."""

    kind: Literal["session_started"] = "session_started"
    net_id: str
    description_id: str | None = None
    description_origin: DescriptionOrigin | None = None
    goal: str = Field(min_length=1)


class UserMessage(DomainModel):
    """A message of the user."""

    kind: Literal["user_message"] = "user_message"
    text: str = Field(min_length=1)


class AssistantMessage(DomainModel):
    """Text written by the LLM. It is labelled as such: never a verdict, never a fact of the net."""

    kind: Literal["assistant_message"] = "assistant_message"
    source: Literal["llm"] = "llm"
    text: str


class ToolCall(DomainModel):
    """The LLM asked for a tool; ``arguments`` is the JSON text it gave."""

    kind: Literal["tool_call"] = "tool_call"
    call_id: str
    tool: str
    arguments: str


class ToolResult(DomainModel):
    """What a tool answered, as text, exactly as the model saw it (ADR 0017)."""

    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    tool: str
    ok: bool
    content: str


class PropertyProposed(DomainModel):
    """A property the LLM proposes to check, with its reason."""

    kind: Literal["property_proposed"] = "property_proposed"
    formula: Formula
    rationale: str = ""


class CheckSubmitted(DomainModel):
    """A check was queued on the platform for some formulas."""

    kind: Literal["check_submitted"] = "check_submitted"
    job_id: str
    formula_ids: tuple[str, ...]


class Verdict(DomainModel):
    """The verdict an engine gave: the only way a verdict enters a conversation (ADR 0006).

    It refers to the job and the result of the engine that produced it, and names the engine and
    its version. It cannot be built without them.
    """

    kind: Literal["verdict"] = "verdict"
    job_id: str = Field(min_length=1)
    result_index: int = Field(ge=0)
    formula_id: str = Field(min_length=1)
    verdict: VerdictValue
    engine: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    has_trace: bool = False


class Question(DomainModel):
    """The LLM asks the user something; the session waits for the answer."""

    kind: Literal["question"] = "question"
    question_id: str
    text: str = Field(min_length=1)


class Answer(DomainModel):
    """The answer of the user to an open question."""

    kind: Literal["answer"] = "answer"
    question_id: str
    text: str = Field(min_length=1)


class BudgetExhausted(DomainModel):
    """The run stopped because it reached a budget."""

    kind: Literal["budget_exhausted"] = "budget_exhausted"
    budget: Literal["steps", "tool_calls", "tokens", "wall_time"]


class SessionError(DomainModel):
    """The run failed for a reason that is not the user's."""

    kind: Literal["session_error"] = "session_error"
    code: str
    message: str


class RunFinished(DomainModel):
    """The agent ended its turn."""

    kind: Literal["run_finished"] = "run_finished"
    reason: Literal["completed", "waiting_for_user", "budget_exhausted", "error", "cancelled"]


class SessionCancelled(DomainModel):
    """The user cancelled the session."""

    kind: Literal["session_cancelled"] = "session_cancelled"


SessionEvent = Annotated[
    SessionStarted
    | UserMessage
    | AssistantMessage
    | ToolCall
    | ToolResult
    | PropertyProposed
    | CheckSubmitted
    | Verdict
    | Question
    | Answer
    | BudgetExhausted
    | SessionError
    | RunFinished
    | SessionCancelled,
    Field(discriminator="kind"),
]


class StoredEvent(DomainModel):
    """An event with its place in the session: numbers start at 1 and only grow by one."""

    session_id: str
    number: int = Field(ge=1)
    at: float
    event: SessionEvent


class StartedSession(DomainModel):
    """A session just created, with its first event."""

    session: Session
    first_event: StoredEvent
