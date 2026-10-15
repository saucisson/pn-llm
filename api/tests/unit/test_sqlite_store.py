import pytest

from app.domain.canonical import net_id_of
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import FormulaResult, Job, JobState, Verdict
from app.domain.nets import summarize_document
from app.infrastructure.sqlite_store import SqliteStore
from tests.support import LEASE, MUTEX_DOCUMENT, make_request, query


def make_job(*, net_id, job_id="j1", **overrides):
    return Job(
        job_id=job_id, net_id=net_id, state=JobState.QUEUED, request=make_request(**overrides)
    )


def save_mutex(*, store):
    document = MUTEX_DOCUMENT
    summary = summarize_document(document=document, net_id=net_id_of(document=document))
    return store.save_net(summary=summary, document=document)


@pytest.fixture
def net_id(store):
    return save_mutex(store=store).stored.summary.net_id


# ---- nets -----------------------------------------------------------------------------------


def test_net_round_trip_keeps_the_canonical_document(store, net_id):
    stored = store.load_net(net_id=net_id)
    assert stored.document == MUTEX_DOCUMENT.sorted_by_id()
    assert net_id_of(document=stored.document) == net_id
    assert stored.summary.places == 3


def test_the_second_save_of_a_net_is_not_a_creation(store, net_id):
    first = save_mutex(store=store)
    assert first.created is False
    assert first.stored.summary.net_id == net_id


def test_the_first_save_of_a_net_is_a_creation(store):
    assert save_mutex(store=store).created is True


def test_the_document_is_stored_compressed(store, net_id, settings):

    raw = query(path=settings.database_path, sql="SELECT document FROM nets")[0][0]
    assert raw[:1] == b"x"  # zlib header
    assert b"idle1" not in raw


def test_unknown_net_raises(store):
    with pytest.raises(NotFoundError):
        store.load_net(net_id="nope")


# ---- jobs -----------------------------------------------------------------------------------


def test_job_round_trip(store, net_id):
    submission = store.create_or_get_job(job=make_job(net_id=net_id))
    assert submission.created
    assert store.load_job(job_id="j1") == submission.job


def test_unknown_job_raises(store):
    with pytest.raises(NotFoundError):
        store.load_job(job_id="nope")


def test_equivalent_live_job_is_reused(store, net_id):
    first = store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"))
    second = store.create_or_get_job(job=make_job(net_id=net_id, job_id="b"))
    assert (first.created, second.created) == (True, False)
    assert second.job.job_id == first.job.job_id == "a"


def test_different_limits_make_a_different_job(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"))
    other = store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="b", limits={"timeout_s": 5, "memory_mb": 128}),
    )
    assert other.created
    assert other.job.job_id == "b"


def test_a_different_net_makes_a_different_job(store, net_id):
    other_document = MUTEX_DOCUMENT.model_copy(update={"source_id": "other"})
    other_id = net_id_of(document=other_document)
    other_net = store.save_net(
        summary=summarize_document(document=other_document, net_id=other_id),
        document=other_document,
    ).stored
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"))
    other = store.create_or_get_job(job=make_job(net_id=other_net.summary.net_id, job_id="b"))
    assert other.created


def test_cancelled_job_is_not_reused(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"))
    store.cancel(job_id="a")
    fresh = store.create_or_get_job(job=make_job(net_id=net_id, job_id="b"))
    assert fresh.created
    assert fresh.job.job_id == "b"


def test_claiming_takes_the_oldest_queued_job_once(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="first", engine="dummy"))
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="second", engine="itstools"))
    one = store.claim_next_job(lease_seconds=LEASE)
    two = store.claim_next_job(lease_seconds=LEASE)
    assert [one.job_id, two.job_id] == ["first", "second"]
    assert store.claim_next_job(lease_seconds=LEASE) is None
    assert store.load_job(job_id="first").state is JobState.RUNNING


def test_a_cancelled_job_is_not_claimed(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.cancel(job_id="j1")
    assert store.claim_next_job(lease_seconds=LEASE) is None


def test_an_empty_queue_claims_nothing(store):
    assert store.claim_next_job(lease_seconds=LEASE) is None


def test_requeue_puts_an_interrupted_job_back_in_the_queue(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.claim_next_job(lease_seconds=-1)
    store.recover_interrupted()
    assert store.requeue(job_id="j1") is True
    assert store.load_job(job_id="j1").state is JobState.QUEUED
    assert store.claim_next_job(lease_seconds=LEASE).job_id == "j1"


def test_only_an_interrupted_job_can_be_requeued(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    assert store.requeue(job_id="j1") is False  # queued
    store.claim_next_job(lease_seconds=LEASE)
    assert store.requeue(job_id="j1") is False  # running


def test_requeue_is_refused_while_an_equivalent_job_is_live(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="old"))
    store.claim_next_job(lease_seconds=-1)
    store.recover_interrupted()
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="new"))  # takes the key
    with pytest.raises(ConflictError):
        store.requeue(job_id="old")
    assert store.load_job(job_id="old").state is JobState.INTERRUPTED


def test_finish_stores_results_and_marks_done(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.claim_next_job(lease_seconds=LEASE)
    result = FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x", warnings=("w",))
    store.finish(traces=(), job_id="j1", results=(result,))
    job = store.load_job(job_id="j1")
    assert job.state is JobState.DONE
    assert job.results == (result,)


def test_finish_does_not_resurrect_a_cancelled_job(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.cancel(job_id="j1")
    store.finish(
        traces=(), job_id="j1", results=(FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x"),)
    )
    job = store.load_job(job_id="j1")
    assert job.state is JobState.CANCELLED
    assert job.results == ()


def test_cancelling_a_finished_job_changes_nothing(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.claim_next_job(lease_seconds=LEASE)
    store.finish(traces=(), job_id="j1", results=())
    store.cancel(job_id="j1")
    assert store.load_job(job_id="j1").state is JobState.DONE


def test_recovery_interrupts_only_running_jobs_whose_lease_expired(store, net_id):
    # A negative lease is already expired: no clock to fake.
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="stale-running", engine="itstools"))
    store.claim_next_job(lease_seconds=-1)
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="alive", engine="tapaal"))
    store.claim_next_job(lease_seconds=LEASE)
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="done", engine="smpt"))
    store.claim_next_job(lease_seconds=LEASE)
    store.finish(traces=(), job_id="done", results=())
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="waiting", engine="dummy"))

    assert store.recover_interrupted() == 1
    assert store.load_job(job_id="stale-running").state is JobState.INTERRUPTED
    assert store.load_job(job_id="alive").state is JobState.RUNNING
    assert store.load_job(job_id="done").state is JobState.DONE
    assert store.load_job(job_id="waiting").state is JobState.QUEUED  # a queue has no lease


def test_renewing_a_lease_keeps_a_job_out_of_recovery(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.claim_next_job(lease_seconds=-1)
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is True
    assert store.recover_interrupted() == 0


def test_renewal_is_refused_once_the_job_is_not_running(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is False  # still queued
    store.claim_next_job(lease_seconds=LEASE)
    store.cancel(job_id="j1")
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is False


def test_an_expired_job_cannot_be_finished_by_its_former_owner(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.claim_next_job(lease_seconds=-1)
    store.recover_interrupted()
    store.finish(
        traces=(), job_id="j1", results=(FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x"),)
    )
    job = store.load_job(job_id="j1")
    assert job.state is JobState.INTERRUPTED
    assert job.results == ()


def test_an_interrupted_job_frees_its_idempotency_key(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"))
    store.claim_next_job(lease_seconds=-1)
    store.recover_interrupted()
    again = store.create_or_get_job(job=make_job(net_id=net_id, job_id="b"))
    assert again.created is True


# ---- several processes sharing one database --------------------------------------------------


def test_only_one_of_two_processes_claims_a_job(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    store.create_or_get_job(job=make_job(net_id=net_id))
    claims = [
        store.claim_next_job(lease_seconds=LEASE),
        other_process.claim_next_job(lease_seconds=LEASE),
    ]
    assert sorted(claim is None for claim in claims) == [False, True]


def test_a_sweep_by_another_process_spares_live_jobs_and_finds_dead_ones(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="live"))
    store.claim_next_job(lease_seconds=LEASE)
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="dead", engine="itstools"))
    store.claim_next_job(lease_seconds=-1)

    assert other_process.recover_interrupted() == 1
    assert store.load_job(job_id="live").state is JobState.RUNNING
    assert store.load_job(job_id="dead").state is JobState.INTERRUPTED


def test_cancelling_from_another_process_is_seen_by_the_owner(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    store.create_or_get_job(job=make_job(net_id=net_id))
    store.claim_next_job(lease_seconds=LEASE)
    other_process.cancel(job_id="j1")
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is False


def test_data_survives_reopening_the_database(settings, net_id):
    reopened = SqliteStore(path=settings.database_path)
    assert reopened.load_net(net_id=net_id).summary.net_id == net_id
