import sqlite3

import pytest

from app.application.agent import AgentConfig, AgentService
from app.application.checks import CheckService
from app.application.formulas import FormulaService
from app.application.inspection import InspectionService
from app.application.retention import RetentionService
from app.application.tools import ToolFacade
from app.domain.canonical import net_id_of
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import FormulaResult, Job, JobState, Verdict
from app.domain.nets import summarize_document
from app.domain.sessions import Session, SessionStarted, SessionState, UserMessage
from app.infrastructure.scripted_llm import ScriptedLlm
from app.infrastructure.sqlite_retention import SqliteRetention
from tests.support import (
    LEASE,
    MUTEX_DOCUMENT,
    ScriptedEngines,
    make_analysis_tools,
    make_request,
    query,
)


@pytest.fixture
def net_id(store):
    net = net_id_of(document=MUTEX_DOCUMENT)
    store.save_net(
        summary=summarize_document(document=MUTEX_DOCUMENT, net_id=net), document=MUTEX_DOCUMENT
    )
    return net


@pytest.fixture
def retention_repo(settings, store):
    return SqliteRetention(path=settings.database_path)


@pytest.fixture
def service(store, retention_repo):
    checks = CheckService(nets=store, jobs=store, engines=ScriptedEngines(), lease_seconds=LEASE)
    tools = ToolFacade(
        inspection=InspectionService(nets=store),
        formulas=FormulaService(nets=store),
        checks=checks,
        analyses=make_analysis_tools(store=store, path=store._path),
        max_result_chars=20_000,
        poll_seconds=0.001,
    )
    agent = AgentService(
        sessions=store,
        descriptions=store,
        nets=store,
        llm=ScriptedLlm(steps=()),
        tools=tools,
        config=AgentConfig(
            max_steps=5, max_tool_calls=5, max_tokens=1000, max_seconds=10, lease_seconds=LEASE
        ),
    )
    return RetentionService(
        retention=retention_repo, agent=agent, nets=store, descriptions=store
    ), agent


def open_session(store, net_id, *, session_id="s1", state=SessionState.IDLE, at=1.0):
    store.create_session(
        session=Session(
            session_id=session_id, net_id=net_id, state=state, created_at=at, updated_at=at
        ),
        started=SessionStarted(net_id=net_id, goal="g"),
    )
    store.append_event(session_id=session_id, event=UserMessage(text="hello"))


def count(settings, table):
    return query(path=settings.database_path, sql=f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - fixed names


def test_a_session_is_deleted_with_its_events(settings, store, net_id, service):
    retention, _ = service
    open_session(store, net_id)
    retention.delete_session(session_id="s1")
    with pytest.raises(NotFoundError):
        store.load_session(session_id="s1")
    assert count(settings, "events") == 0
    with pytest.raises(NotFoundError):
        retention.delete_session(session_id="s1")


def test_deleting_a_queued_session_cancels_it_first(store, net_id, service):
    retention, _ = service
    open_session(store, net_id, state=SessionState.QUEUED)
    retention.delete_session(session_id="s1")
    with pytest.raises(NotFoundError):
        store.load_session(session_id="s1")


def test_a_net_in_use_is_kept_unless_cascade_is_asked(settings, store, net_id, service):
    retention, _ = service
    open_session(store, net_id)
    store.create_or_get_job(
        job=Job(job_id="j", net_id=net_id, state=JobState.QUEUED, request=make_request())
    )
    store.claim_next_job(lease_seconds=LEASE)
    store.finish(
        job_id="j", results=(FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x"),), traces=()
    )
    store.save_description(net_id=net_id, text="about", origin="user")

    with pytest.raises(ConflictError, match="cascade"):
        retention.delete_net(net_id=net_id, cascade=False)
    retention.delete_net(net_id=net_id, cascade=True)

    for table in ("nets", "jobs", "sessions", "events", "net_descriptions", "descriptions"):
        assert count(settings, table) == 0, table


def test_a_net_with_running_work_is_never_deleted(store, net_id, service):
    retention, _ = service
    open_session(store, net_id, state=SessionState.RUNNING)
    with pytest.raises(ConflictError, match="running"):
        retention.delete_net(net_id=net_id, cascade=True)


def test_an_unused_net_is_deleted_without_cascade(settings, store, net_id, service):
    retention, _ = service
    retention.delete_net(net_id=net_id, cascade=False)
    assert count(settings, "nets") == 0
    with pytest.raises(NotFoundError):
        retention.delete_net(net_id=net_id, cascade=False)


def test_a_description_goes_when_no_net_links_to_it(settings, store, net_id, service):
    retention, _ = service
    store.save_description(net_id=net_id, text="shared text", origin="user")
    store.save_description(net_id=net_id, text="shared text", origin="mcc")
    description_id = store.descriptions_of(net_id=net_id)[0].description_id
    retention.delete_description(description_id=description_id, net_id=net_id)
    assert count(settings, "descriptions") == 0
    with pytest.raises(NotFoundError):
        retention.delete_description(description_id=description_id, net_id=net_id)


def test_a_description_used_by_another_net_stays(settings, store, net_id, service):
    retention, _ = service
    other_doc = MUTEX_DOCUMENT.model_copy(update={"source_id": "other"})
    other = net_id_of(document=other_doc)
    store.save_net(summary=summarize_document(document=other_doc, net_id=other), document=other_doc)
    store.save_description(net_id=net_id, text="shared", origin="user")
    store.save_description(net_id=other, text="shared", origin="user")
    description_id = store.descriptions_of(net_id=net_id)[0].description_id
    retention.delete_description(description_id=description_id, net_id=net_id)
    assert count(settings, "descriptions") == 1
    assert store.descriptions_of(net_id=other)[0].text == "shared"


def test_old_idle_sessions_expire_but_live_and_recent_ones_stay(settings, store, net_id, service):
    retention, _ = service
    open_session(store, net_id, session_id="old", state=SessionState.IDLE)
    open_session(store, net_id, session_id="running", state=SessionState.RUNNING)
    open_session(store, net_id, session_id="queued", state=SessionState.QUEUED)
    conn = sqlite3.connect(settings.database_path)
    conn.execute("UPDATE sessions SET updated_at=0")
    conn.commit()
    conn.close()
    open_session(store, net_id, session_id="recent", state=SessionState.IDLE, at=10**10)

    assert retention.expire(sessions_older_than_s=86_400, nets_older_than_s=None) == 1
    assert {
        row[0] for row in query(path=settings.database_path, sql="SELECT session_id FROM sessions")
    } == {
        "running",
        "queued",
        "recent",
    }


def test_unreferenced_nets_expire_after_their_delay_and_used_ones_stay(
    settings, store, net_id, service
):
    retention, _ = service
    unused_doc = MUTEX_DOCUMENT.model_copy(update={"source_id": "unused"})
    unused = net_id_of(document=unused_doc)
    store.save_net(
        summary=summarize_document(document=unused_doc, net_id=unused), document=unused_doc
    )
    store.save_description(net_id=unused, text="orphan text", origin="user")
    open_session(store, net_id)  # the first net is used
    conn = sqlite3.connect(settings.database_path)
    conn.execute("UPDATE nets SET created_at=0")
    conn.commit()
    conn.close()

    assert retention.expire(sessions_older_than_s=None, nets_older_than_s=86_400) == 1
    assert {
        row[0] for row in query(path=settings.database_path, sql="SELECT net_id FROM nets")
    } == {net_id}
    assert count(settings, "descriptions") == 0


def test_nothing_expires_without_a_policy(store, net_id, service):
    retention, _ = service
    open_session(store, net_id)
    assert retention.expire(sessions_older_than_s=None, nets_older_than_s=None) == 0
