import threading

import pytest

from app.domain.canonical import net_id_of
from app.domain.errors import NotFoundError
from app.domain.nets import summarize_document
from app.domain.sessions import (
    Session,
    SessionStarted,
    SessionState,
    UserMessage,
)
from app.infrastructure.sqlite_store import SqliteStore
from tests.support import LEASE, MUTEX_DOCUMENT


@pytest.fixture
def net_id(store):
    net = net_id_of(document=MUTEX_DOCUMENT)
    store.save_net(
        summary=summarize_document(document=MUTEX_DOCUMENT, net_id=net), document=MUTEX_DOCUMENT
    )
    return net


def make_session(*, net_id, session_id="s1", state=SessionState.QUEUED, at=1.0):
    return Session(session_id=session_id, net_id=net_id, state=state, created_at=at, updated_at=at)


def start(*, store, net_id, session_id="s1", at=1.0):
    return store.create_session(
        session=make_session(net_id=net_id, session_id=session_id, at=at),
        started=SessionStarted(net_id=net_id, goal="check mutual exclusion"),
    )


def test_a_session_is_created_with_its_first_event(store, net_id):
    started = start(store=store, net_id=net_id)
    assert started.first_event.number == 1
    assert started.first_event.event.kind == "session_started"
    assert store.load_session(session_id="s1") == started.session
    assert store.events_after(session_id="s1", after=0, limit=10) == (started.first_event,)


def test_an_unknown_session_is_not_found(store):
    with pytest.raises(NotFoundError):
        store.load_session(session_id="nope")


def test_event_numbers_are_consecutive_and_events_can_be_read_after_a_number(store, net_id):
    start(store=store, net_id=net_id)
    numbers = [
        store.append_event(session_id="s1", event=UserMessage(text=f"m{i}")).number
        for i in range(4)
    ]
    assert numbers == [2, 3, 4, 5]
    tail = store.events_after(session_id="s1", after=3, limit=10)
    assert [e.number for e in tail] == [4, 5]
    assert [e.number for e in store.events_after(session_id="s1", after=0, limit=2)] == [1, 2]
    assert store.events_after(session_id="s1", after=5, limit=10) == ()


def test_each_session_has_its_own_numbering(store, net_id):
    start(store=store, net_id=net_id, session_id="a")
    start(store=store, net_id=net_id, session_id="b")
    store.append_event(session_id="a", event=UserMessage(text="x"))
    assert store.append_event(session_id="b", event=UserMessage(text="y")).number == 2


def test_two_store_instances_writing_at_once_never_share_or_skip_a_number(settings, store, net_id):
    start(store=store, net_id=net_id)
    other_process = SqliteStore(path=settings.database_path)
    errors = []

    def write(target, count):
        try:
            for _ in range(count):
                target.append_event(session_id="s1", event=UserMessage(text="x"))
        except Exception as exc:  # noqa: BLE001 - collected to fail the test with the cause
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(target, 15))
        for target in (store, other_process, store, other_process)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    numbers = [e.number for e in store.events_after(session_id="s1", after=0, limit=1000)]
    assert numbers == list(range(1, 62))


def test_events_survive_reopening_the_database(settings, store, net_id):
    start(store=store, net_id=net_id)
    store.append_event(session_id="s1", event=UserMessage(text="kept"))
    reopened = SqliteStore(path=settings.database_path)
    texts = [e.event for e in reopened.events_after(session_id="s1", after=1, limit=5)]
    assert texts == [UserMessage(text="kept")]


def test_moving_a_session_only_from_allowed_states(store, net_id):
    start(store=store, net_id=net_id)
    assert (
        store.move_session(
            session_id="s1", allowed_from=(SessionState.IDLE,), to=SessionState.QUEUED
        )
        is False
    )
    assert (
        store.move_session(
            session_id="s1",
            allowed_from=(SessionState.QUEUED, SessionState.IDLE),
            to=SessionState.IDLE,
        )
        is True
    )
    assert store.load_session(session_id="s1").state is SessionState.IDLE


def test_claiming_takes_the_oldest_queued_session_once_and_runs_it(store, net_id):
    start(store=store, net_id=net_id, session_id="late", at=5.0)
    start(store=store, net_id=net_id, session_id="early", at=2.0)
    first = store.claim_next_run(lease_seconds=LEASE)
    second = store.claim_next_run(lease_seconds=LEASE)
    assert [first.session_id, second.session_id] == ["early", "late"]
    assert first.state is SessionState.RUNNING
    assert store.claim_next_run(lease_seconds=LEASE) is None


def test_only_one_of_two_processes_claims_a_run(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    start(store=store, net_id=net_id)
    claims = [
        store.claim_next_run(lease_seconds=LEASE),
        other_process.claim_next_run(lease_seconds=LEASE),
    ]
    assert sorted(claim is None for claim in claims) == [False, True]


def test_a_run_ends_only_if_it_is_still_running(store, net_id):
    start(store=store, net_id=net_id)
    assert store.finish_run(session_id="s1", to=SessionState.IDLE) is False  # queued
    store.claim_next_run(lease_seconds=LEASE)
    store.move_session(
        session_id="s1", allowed_from=(SessionState.RUNNING,), to=SessionState.CANCELLED
    )
    assert store.finish_run(session_id="s1", to=SessionState.IDLE) is False
    assert store.load_session(session_id="s1").state is SessionState.CANCELLED


def test_a_lost_run_is_queued_again_and_a_live_one_is_left_alone(store, net_id):
    start(store=store, net_id=net_id, session_id="lost", at=1.0)
    store.claim_next_run(lease_seconds=-1)
    start(store=store, net_id=net_id, session_id="live", at=2.0)
    store.claim_next_run(lease_seconds=LEASE)
    start(store=store, net_id=net_id, session_id="waiting", at=3.0)

    assert store.requeue_lost_runs() == 1
    assert store.load_session(session_id="lost").state is SessionState.QUEUED
    assert store.load_session(session_id="live").state is SessionState.RUNNING
    assert store.load_session(session_id="waiting").state is SessionState.QUEUED


def test_renewing_the_lease_keeps_a_run_out_of_recovery(store, net_id):
    start(store=store, net_id=net_id)
    store.claim_next_run(lease_seconds=-1)
    assert store.renew_run_lease(session_id="s1", lease_seconds=LEASE) is True
    assert store.requeue_lost_runs() == 0
    store.move_session(session_id="s1", allowed_from=(SessionState.RUNNING,), to=SessionState.IDLE)
    assert store.renew_run_lease(session_id="s1", lease_seconds=LEASE) is False
