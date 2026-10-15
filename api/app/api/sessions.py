"""Routes about sessions: the chat with the agent (ADR 0008, ADR 0010).

Commands are ordinary ``POST``s. The events are read from the database, as JSON or as a stream of
server-sent events that a client resumes with ``Last-Event-ID``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app.domain.contract import Envelope
from app.domain.models import DomainModel
from app.domain.nets import NetFormat
from app.domain.report import SessionReport, render_markdown
from app.domain.sessions import Session, StoredEvent

from .deps import AgentDep, DescriptionsDep, NetsDep, RetentionDep
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


@router.post("/upload", status_code=HTTPStatus.CREATED)
async def start_session_with_files(  # noqa: PLR0913 - one field per input of the form
    *,
    nets: NetsDep,
    descriptions: DescriptionsDep,
    agent: AgentDep,
    response: Response,
    goal: Annotated[str, Form(min_length=1, max_length=MAX_USER_TEXT)],
    net: Annotated[UploadFile, File(description="PNML, or a JSON net document (.json)")],
    description: Annotated[str | None, Form()] = None,
    description_file: Annotated[UploadFile | None, File(description=".txt or .md")] = None,
) -> Envelope[Session]:
    """Register the net, store the description, and open the session: one request.

    A description typed in the form wins over a description file. Nothing is attached to the
    (immutable) net except the description, linked with the origin ``user``.
    """
    started = time.perf_counter()
    payload = await net.read()
    is_json = (net.filename or "").lower().endswith(".json")
    registered = await run_in_threadpool(
        nets.register, payload=payload, format=NetFormat.JSON if is_json else NetFormat.PNML
    )
    net_id = registered.stored.summary.net_id
    description_id = None
    text = description.encode() if description else b""
    if not text and description_file is not None:
        text = await description_file.read()
    if text:
        saved = await run_in_threadpool(
            descriptions.add, net_id=net_id, payload=text, origin="user"
        )
        description_id = saved.description.description_id
    created = await run_in_threadpool(
        agent.start, net_id=net_id, description_id=description_id, goal=goal
    )
    response.headers["Location"] = f"/v1/sessions/{created.session.session_id}"
    return wrap(tool="session.start", net_id=net_id, started=started, data=created.session)


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


class RestartRequest(DomainModel):
    """Body of ``POST /v1/sessions/{id}/restart``."""

    with_description: bool = True


@router.post("/{session_id}/restart", status_code=HTTPStatus.CREATED)
def restart_session(
    *, session_id: str, body: RestartRequest, agent: AgentDep, response: Response
) -> Envelope[Session]:
    """Open a new session with the goal of this one, with or without its description."""
    started = time.perf_counter()
    created = agent.restart(session_id=session_id, with_description=body.with_description)
    response.headers["Location"] = f"/v1/sessions/{created.session.session_id}"
    return wrap(
        tool="session.restart", net_id=created.session.net_id, started=started, data=created.session
    )


@router.post(
    "/{session_id}/description-proposals/{proposal_id}/accept", status_code=HTTPStatus.CREATED
)
def accept_description(
    *, session_id: str, proposal_id: str, agent: AgentDep
) -> Envelope[StoredEvent]:
    """Store a description the assistant proposed: only the user's acceptance does it."""
    started = time.perf_counter()
    stored = agent.accept_description(session_id=session_id, proposal_id=proposal_id)
    return wrap(tool="session.accept_description", net_id=None, started=started, data=stored)


@router.delete("/{session_id}", status_code=HTTPStatus.NO_CONTENT)
def delete_session(*, session_id: str, retention: RetentionDep) -> Response:
    """Delete a session and its events (its run is cancelled first)."""
    retention.delete_session(session_id=session_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.post("/{session_id}/cancel")
def cancel_session(*, session_id: str, agent: AgentDep) -> Envelope[Session]:
    """Cancel a session: the run stops and a check in progress is cancelled."""
    started = time.perf_counter()
    session = agent.cancel(session_id=session_id)
    return wrap(tool="session.cancel", net_id=session.net_id, started=started, data=session)


@router.get("/{session_id}/report", response_model=None)
def get_report(
    *,
    session_id: str,
    request: Request,
    agent: AgentDep,
    format: Annotated[  # noqa: A002 - the query parameter is called format
        Literal["json", "markdown"] | None, Query(description="Instead of the Accept header")
    ] = None,
) -> Envelope[SessionReport] | Response:
    """The report of a session: JSON (default), or Markdown with ``Accept: text/markdown``."""
    started = time.perf_counter()
    report = agent.report(session_id=session_id)
    wants_markdown = format == "markdown" or (
        format is None and "text/markdown" in request.headers.get("accept", "")
    )
    if wants_markdown:
        return Response(
            content=render_markdown(report=report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="session-{session_id}.md"'},
        )
    return wrap(tool="session.report", net_id=report.net.net_id, started=started, data=report)


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
