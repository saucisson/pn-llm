"""Routes about sessions: the chat with the agent (ADR 0008, ADR 0010).

Commands are ordinary ``POST``s. The events are read from the database, as JSON or as a stream of
server-sent events that a client resumes with ``Last-Event-ID``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app.domain.contract import Envelope
from app.domain.models import DomainModel
from app.domain.sessions import Session, StoredEvent

from .deps import AgentDep
from .envelopes import wrap

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

STREAM_BATCH = 100
POLL_SECONDS = 0.3
KEEP_ALIVE_SECONDS = 15.0
MAX_USER_TEXT = 8_000


class StartSessionRequest(DomainModel):
    """Body of ``POST /v1/sessions``: the net, an optional description and the goal."""

    net_id: str
    description_id: str | None = None
    goal: str = Field(min_length=1, max_length=MAX_USER_TEXT)


class MessageRequest(DomainModel):
    """Body of ``POST /v1/sessions/{id}/messages``."""

    text: str = Field(min_length=1, max_length=MAX_USER_TEXT)


class AnswerRequest(DomainModel):
    """Body of ``POST /v1/sessions/{id}/answers``: the open question and the answer."""

    question_id: str
    text: str = Field(min_length=1, max_length=MAX_USER_TEXT)


@router.post("", status_code=HTTPStatus.CREATED)
def start_session(
    *, body: StartSessionRequest, agent: AgentDep, response: Response
) -> Envelope[Session]:
    """Open a session on a net; the agent starts working at once."""
    started = time.perf_counter()
    created = agent.start(net_id=body.net_id, description_id=body.description_id, goal=body.goal)
    response.headers["Location"] = f"/v1/sessions/{created.session.session_id}"
    return wrap(tool="session.start", net_id=body.net_id, started=started, data=created.session)


@router.get("/{session_id}")
def get_session(*, session_id: str, agent: AgentDep) -> Envelope[Session]:
    """The state of a session."""
    started = time.perf_counter()
    session = agent.get(session_id=session_id)
    return wrap(tool="session.get", net_id=session.net_id, started=started, data=session)


@router.post("/{session_id}/messages", status_code=HTTPStatus.ACCEPTED)
def post_message(
    *, session_id: str, body: MessageRequest, agent: AgentDep
) -> Envelope[StoredEvent]:
    """Add a message once the agent has finished its turn."""
    started = time.perf_counter()
    stored = agent.post_message(session_id=session_id, text=body.text)
    return wrap(tool="session.message", net_id=None, started=started, data=stored)


@router.post("/{session_id}/answers", status_code=HTTPStatus.ACCEPTED)
def post_answer(*, session_id: str, body: AnswerRequest, agent: AgentDep) -> Envelope[StoredEvent]:
    """Answer the question the agent is waiting on."""
    started = time.perf_counter()
    stored = agent.answer(session_id=session_id, question_id=body.question_id, text=body.text)
    return wrap(tool="session.answer", net_id=None, started=started, data=stored)


@router.post("/{session_id}/cancel")
def cancel_session(*, session_id: str, agent: AgentDep) -> Envelope[Session]:
    """Cancel a session: the run stops and a check in progress is cancelled."""
    started = time.perf_counter()
    session = agent.cancel(session_id=session_id)
    return wrap(tool="session.cancel", net_id=session.net_id, started=started, data=session)


@router.get("/{session_id}/events", response_model=None)
async def get_events(
    *,
    session_id: str,
    request: Request,
    agent: AgentDep,
    after: Annotated[int | None, Query(ge=0, description="Events after this number")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    follow: Annotated[bool, Query(description="Stream: keep the connection open")] = True,
) -> Envelope[tuple[StoredEvent, ...]] | StreamingResponse:
    """The events of a session: JSON, or a stream with ``Accept: text/event-stream``.

    A stream resumes after ``after`` or after the ``Last-Event-ID`` header; without ``follow`` it
    ends when there is nothing more to send.
    """
    started = time.perf_counter()
    header = request.headers.get("last-event-id", "")
    first = after if after is not None else (int(header) if header.isdigit() else 0)
    await run_in_threadpool(agent.get, session_id=session_id)  # 404 before any streaming
    if "text/event-stream" not in request.headers.get("accept", ""):
        found = await run_in_threadpool(
            agent.events, session_id=session_id, after=first, limit=limit
        )
        return wrap(tool="session.events", net_id=None, started=started, data=found)

    async def stream() -> AsyncIterator[str]:
        position = first
        quiet_for = 0.0
        while not await request.is_disconnected():
            batch = await run_in_threadpool(
                agent.events, session_id=session_id, after=position, limit=STREAM_BATCH
            )
            for stored in batch:
                position = stored.number
                yield (
                    f"id: {stored.number}\nevent: {stored.event.kind}\n"
                    f"data: {stored.model_dump_json()}\n\n"
                )
            if batch:
                quiet_for = 0.0
                continue
            if not follow:
                return
            quiet_for += POLL_SECONDS
            if quiet_for >= KEEP_ALIVE_SECONDS:
                yield ": keep-alive\n\n"
                quiet_for = 0.0
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
