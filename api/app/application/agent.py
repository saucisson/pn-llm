"""The agent: a session's conversation with the LLM, run by workers (ADR 0008, ADR 0009).

A user message or an answer queues a run. A worker claims it atomically and keeps a lease. The
run is event-sourced: it rebuilds what the model sees from the events of the session, so a run
that was lost resumes where it stopped. Every step of the model is recorded as events; the only
verdicts in the log are those that tools took from engine results (ADR 0006).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Literal

from app.domain.conversation import (
    ASK_USER_TOOL,
    SYSTEM_PROMPT,
    build_messages,
    compact,
)
from app.domain.descriptions import Description
from app.domain.errors import ConflictError, InvalidRequestError, LlmUnavailableError
from app.domain.llm import LlmToolCall
from app.domain.models import DomainModel
from app.domain.report import SessionReport, build_report
from app.domain.sessions import (
    Answer,
    AssistantMessage,
    BudgetExhausted,
    DescriptionAccepted,
    DescriptionProposed,
    Question,
    RunFinished,
    Session,
    SessionCancelled,
    SessionError,
    SessionEvent,
    SessionStarted,
    SessionState,
    StartedSession,
    StoredEvent,
    ToolCall,
    ToolResult,
    UserMessage,
)

from .leases import LeaseKeeper
from .ports import DescriptionRepository, LlmGateway, NetRepository, SessionRepository
from .tool_kit import ToolContext
from .tools import ToolFacade

SESSION_ID_LENGTH = 12

logger = logging.getLogger("pnverif.agent")
EVENT_PAGE = 500
# Events a tool may add to the conversation. A verdict is among them, built by the tool from an
# engine result: the model has no way to write one.
TOOL_EVENT_KINDS = frozenset(
    {"property_proposed", "check_submitted", "verdict", "question", "description_proposed"}
)
LIVE_STATES = (
    SessionState.QUEUED,
    SessionState.RUNNING,
    SessionState.WAITING_FOR_USER,
    SessionState.IDLE,
)


class AgentConfig(DomainModel):
    """Limits of one run (reaching one ends it with a ``budget_exhausted`` event) and its lease."""

    max_steps: int
    max_tool_calls: int
    max_tokens: int
    max_seconds: float
    lease_seconds: float
    # Tool results older than this many are shortened in what the model sees.
    keep_recent_results: int = 6
    head_chars: int = 400


def exhausted_budget(
    *, config: AgentConfig, steps: int, tokens: int, elapsed_s: float
) -> Literal["steps", "tokens", "wall_time"] | None:
    """Return the budget a run has just used up, if any."""
    if steps >= config.max_steps:
        return "steps"
    if tokens >= config.max_tokens:
        return "tokens"
    if elapsed_s >= config.max_seconds:
        return "wall_time"
    return None


class CallsOutcome(DomainModel):
    """What came of running the tool calls of one step."""

    executed: int
    waiting: bool = False
    out_of_calls: bool = False


class AgentService:
    """Start sessions, take the user's messages and answers, and run the agent."""

    def __init__(
        self,
        *,
        sessions: SessionRepository,
        descriptions: DescriptionRepository,
        nets: NetRepository,
        llm: LlmGateway,
        tools: ToolFacade,
        config: AgentConfig,
    ) -> None:
        """Create the service over its ports and the facade of tools."""
        self._sessions = sessions
        self._descriptions = descriptions
        self._nets = nets
        self._llm = llm
        self._tools = tools
        self._config = config

    # ---- what the user does ---------------------------------------------------------------

    def start(self, *, net_id: str, description_id: str | None, goal: str) -> StartedSession:
        """Open a session on a net with the user's goal and, optionally, a description.

        Raises:
            NotFoundError: if the net or the description is unknown.
            InvalidRequestError: if the description is not linked to this net.
        """
        self._nets.load_net(net_id=net_id)
        origin = None
        if description_id is not None:
            links = self._descriptions.load_description(description_id=description_id)
            linked = [link for link in links if link.net_id == net_id]
            if not linked:
                raise InvalidRequestError("That description is not linked to this net")
            origin = linked[0].origin
        now = time.time()
        session = Session(
            session_id=uuid.uuid4().hex[:SESSION_ID_LENGTH],
            net_id=net_id,
            description_id=description_id,
            state=SessionState.QUEUED,
            created_at=now,
            updated_at=now,
        )
        started = SessionStarted(
            net_id=net_id, description_id=description_id, description_origin=origin, goal=goal
        )
        return self._sessions.create_session(session=session, started=started)

    def report(self, *, session_id: str) -> SessionReport:
        """Build the report of a session from its events.

        Raises:
            NotFoundError: if the session is unknown.
        """
        session = self._sessions.load_session(session_id=session_id)
        description = None
        if session.description_id is not None:
            links = self._descriptions.load_description(description_id=session.description_id)
            description = next((link for link in links if link.net_id == session.net_id), None)
        return build_report(
            session=session,
            net=self._nets.load_net(net_id=session.net_id).summary,
            description=description,
            events=self.all_events(session_id=session_id),
        )

    def restart(self, *, session_id: str, with_description: bool) -> StartedSession:
        """Open a new session with the goal (and, if asked, the description) of an existing one.

        It is how a run is repeated without its description, to compare conditions.

        Raises:
            NotFoundError: if the session is unknown.
        """
        session = self._sessions.load_session(session_id=session_id)
        first = self._sessions.events_after(session_id=session_id, after=0, limit=1)[0].event
        if not isinstance(first, SessionStarted):
            raise InvalidRequestError("The session has no start event")
        return self.start(
            net_id=session.net_id,
            description_id=session.description_id if with_description else None,
            goal=first.goal,
        )

    def accept_description(self, *, session_id: str, proposal_id: str) -> StoredEvent:
        """Store a description the assistant proposed, now that the user accepted it.

        Raises:
            NotFoundError: if the session is unknown.
            InvalidRequestError: if there is no such proposal, or it was accepted already.
        """
        session = self._sessions.load_session(session_id=session_id)
        events = self.all_events(session_id=session_id)
        proposal = next(
            (
                s.event
                for s in events
                if isinstance(s.event, DescriptionProposed) and s.event.proposal_id == proposal_id
            ),
            None,
        )
        if proposal is None:
            raise InvalidRequestError("That is not a description proposed in this session")
        if any(
            isinstance(s.event, DescriptionAccepted) and s.event.proposal_id == proposal_id
            for s in events
        ):
            raise ConflictError("That proposal was accepted already")
        saved = self._descriptions.save_description(
            net_id=session.net_id, text=proposal.text, origin="llm"
        )
        return self._sessions.append_event(
            session_id=session_id,
            event=DescriptionAccepted(
                proposal_id=proposal_id, description_id=saved.description.description_id
            ),
        )

    def get(self, *, session_id: str) -> Session:
        """Return a session.

        Raises:
            NotFoundError: if it is unknown.
        """
        return self._sessions.load_session(session_id=session_id)

    def events(self, *, session_id: str, after: int, limit: int) -> tuple[StoredEvent, ...]:
        """Return events after a number, in order.

        Raises:
            NotFoundError: if the session is unknown.
        """
        self._sessions.load_session(session_id=session_id)
        return self._sessions.events_after(session_id=session_id, after=after, limit=limit)

    def post_message(self, *, session_id: str, text: str) -> StoredEvent:
        """Add a message of the user and queue a run.

        Raises:
            NotFoundError: if the session is unknown.
            ConflictError: if the agent is not waiting for a message (it is working, waiting for an
                answer to a question, or the session is cancelled).
        """
        session = self._sessions.load_session(session_id=session_id)
        if session.state is not SessionState.IDLE:
            raise ConflictError(
                f"The session is {session.state.value}: a message cannot be added now"
            )
        stored = self._sessions.append_event(session_id=session_id, event=UserMessage(text=text))
        if not self._sessions.move_session(
            session_id=session_id, allowed_from=(SessionState.IDLE,), to=SessionState.QUEUED
        ):
            raise ConflictError("The session changed state meanwhile; try again")
        return stored

    def answer(self, *, session_id: str, question_id: str, text: str) -> StoredEvent:
        """Answer the open question of a session and queue a run.

        Raises:
            NotFoundError: if the session is unknown.
            ConflictError: if the session is not waiting for an answer.
            InvalidRequestError: if ``question_id`` is not the open question.
        """
        session = self._sessions.load_session(session_id=session_id)
        if session.state is not SessionState.WAITING_FOR_USER:
            raise ConflictError(f"The session is {session.state.value}: no question is open")
        open_question = self.open_question(session_id=session_id)
        if open_question is None or open_question.question_id != question_id:
            raise InvalidRequestError("That is not the open question of this session")
        stored = self._sessions.append_event(
            session_id=session_id, event=Answer(question_id=question_id, text=text)
        )
        if not self._sessions.move_session(
            session_id=session_id,
            allowed_from=(SessionState.WAITING_FOR_USER,),
            to=SessionState.QUEUED,
        ):
            raise ConflictError("The session changed state meanwhile; try again")
        return stored

    def cancel(self, *, session_id: str) -> Session:
        """Cancel a session: its run stops at the next step and a check in progress is cancelled.

        Cancelling a cancelled session changes nothing.

        Raises:
            NotFoundError: if the session is unknown.
        """
        self._sessions.load_session(session_id=session_id)
        if self._sessions.move_session(
            session_id=session_id, allowed_from=LIVE_STATES, to=SessionState.CANCELLED
        ):
            self._sessions.append_event(session_id=session_id, event=SessionCancelled())
        return self._sessions.load_session(session_id=session_id)

    def open_question(self, *, session_id: str) -> Question | None:
        """Return the question the session is waiting an answer for, if any."""
        events = self.all_events(session_id=session_id)
        answered = {s.event.question_id for s in events if isinstance(s.event, Answer)}
        for stored in reversed(events):
            if isinstance(stored.event, Question) and stored.event.question_id not in answered:
                return stored.event
        return None

    def all_events(self, *, session_id: str) -> tuple[StoredEvent, ...]:
        """Return every event of a session."""
        found: list[StoredEvent] = []
        while True:
            page = self._sessions.events_after(
                session_id=session_id, after=found[-1].number if found else 0, limit=EVENT_PAGE
            )
            found.extend(page)
            if len(page) < EVENT_PAGE:
                return tuple(found)

    # ---- housekeeping ---------------------------------------------------------------------

    def recover_lost_runs(self) -> int:
        """Queue again the runs whose worker stopped renewing its lease."""
        return self._sessions.requeue_lost_runs()

    def expire_waiting(self, *, older_than_s: float) -> int:
        """Cancel the sessions that waited for the user for longer than ``older_than_s``."""
        expired = self._sessions.expire_waiting_sessions(older_than_s=older_than_s)
        for session_id in expired:
            self._sessions.append_event(session_id=session_id, event=SessionCancelled())
        return len(expired)

    # ---- the run --------------------------------------------------------------------------

    def run_next(self) -> bool:
        """Claim the oldest queued session and run the agent for it; False if none waits."""
        session = self._sessions.claim_next_run(lease_seconds=self._config.lease_seconds)
        if session is None:
            return False
        began = time.monotonic()
        extra = {"session_id": session.session_id, "net_id": session.net_id}
        logger.info("run_started", extra=extra)
        self.run(session=session)
        logger.info(
            "run_finished", extra={**extra, "duration_s": round(time.monotonic() - began, 3)}
        )
        return True

    def record(self, *, session_id: str, event: SessionEvent) -> None:
        """Append an event to the log of a session."""
        self._sessions.append_event(session_id=session_id, event=event)

    def end_run(
        self,
        *,
        session_id: str,
        to: SessionState,
        reason: Literal["completed", "waiting_for_user", "budget_exhausted", "error", "cancelled"],
    ) -> None:
        """Leave the running state and say why, unless the session was cancelled meanwhile."""
        if self._sessions.finish_run(session_id=session_id, to=to):
            self.record(session_id=session_id, event=RunFinished(reason=reason))

    def is_cancelled(self, *, session_id: str, lost: threading.Event) -> bool:
        """Tell whether the session was cancelled or the lease of this run was lost."""
        return (
            lost.is_set()
            or self._sessions.load_session(session_id=session_id).state is SessionState.CANCELLED
        )

    def run_calls(
        self,
        *,
        context: ToolContext,
        calls: tuple[LlmToolCall, ...],
        executed: int,
        lost: threading.Event,
    ) -> CallsOutcome:
        """Run the tool calls of one step, recording each call, its result and its events."""
        session_id = context.session.session_id
        waiting = False
        for call in calls:
            if executed >= self._config.max_tool_calls:
                return CallsOutcome(executed=executed, waiting=waiting, out_of_calls=True)
            executed += 1
            self.record(
                session_id=session_id,
                event=ToolCall(call_id=call.call_id, tool=call.tool, arguments=call.arguments),
            )
            outcome = self._tools.call(
                context=context,
                call=call,
                is_cancelled=lambda: self.is_cancelled(session_id=session_id, lost=lost),
            )
            asking = call.tool == ASK_USER_TOOL and outcome.ok
            if not asking:
                # A question has no result yet: the answer of the user is its result.
                self.record(
                    session_id=session_id,
                    event=ToolResult(
                        call_id=call.call_id, tool=call.tool, ok=outcome.ok, content=outcome.content
                    ),
                )
            for event in outcome.events:
                if event.kind in TOOL_EVENT_KINDS:
                    self.record(session_id=session_id, event=event)
            waiting = waiting or asking
        return CallsOutcome(executed=executed, waiting=waiting)

    def run(self, *, session: Session) -> None:
        """Run the agent until it has nothing more to do, waits for the user or hits a budget."""
        session_id = session.session_id
        lost = threading.Event()
        started = time.monotonic()
        steps = executed = tokens = 0
        description: Description | None = None
        if session.description_id is not None:
            links = self._descriptions.load_description(description_id=session.description_id)
            description = next((link for link in links if link.net_id == session.net_id), None)
        context = ToolContext(session=session, description=description)

        with LeaseKeeper(
            renew=lambda: self._sessions.renew_run_lease(
                session_id=session_id, lease_seconds=self._config.lease_seconds
            ),
            lease_seconds=self._config.lease_seconds,
            on_lost=lost.set,
        ):
            while not self.is_cancelled(session_id=session_id, lost=lost):
                budget = exhausted_budget(
                    config=self._config,
                    steps=steps,
                    tokens=tokens,
                    elapsed_s=time.monotonic() - started,
                )
                if budget is not None:
                    self.record(session_id=session_id, event=BudgetExhausted(budget=budget))
                    self.end_run(
                        session_id=session_id, to=SessionState.IDLE, reason="budget_exhausted"
                    )
                    return

                messages = compact(
                    messages=build_messages(
                        events=self.all_events(session_id=session_id), description=description
                    ),
                    keep_recent=self._config.keep_recent_results,
                    head_chars=self._config.head_chars,
                )
                try:
                    step = self._llm.next_step(
                        system=SYSTEM_PROMPT, messages=messages, tools=self._tools.specs()
                    )
                except Exception as exc:  # noqa: BLE001 - a provider failure ends the run, visibly
                    code = (
                        "llm_unavailable" if isinstance(exc, LlmUnavailableError) else "llm_error"
                    )
                    message = str(exc) if code == "llm_unavailable" else type(exc).__name__
                    self.record(
                        session_id=session_id, event=SessionError(code=code, message=message)
                    )
                    self.end_run(session_id=session_id, to=SessionState.IDLE, reason="error")
                    return
                steps += 1
                tokens += step.input_tokens + step.output_tokens
                if step.text:
                    self.record(session_id=session_id, event=AssistantMessage(text=step.text))
                if not step.tool_calls:
                    self.end_run(session_id=session_id, to=SessionState.IDLE, reason="completed")
                    return

                done = self.run_calls(
                    context=context, calls=step.tool_calls, executed=executed, lost=lost
                )
                executed = done.executed
                if done.out_of_calls:
                    self.record(session_id=session_id, event=BudgetExhausted(budget="tool_calls"))
                    self.end_run(
                        session_id=session_id, to=SessionState.IDLE, reason="budget_exhausted"
                    )
                    return
                if done.waiting:
                    self.end_run(
                        session_id=session_id,
                        to=SessionState.WAITING_FOR_USER,
                        reason="waiting_for_user",
                    )
                    return
