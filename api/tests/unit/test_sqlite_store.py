import pytest

from app.domain import pnml
from app.domain.errors import NotFoundError
from app.domain.models import FormulaResult, Job, JobState, Verdict
from app.infrastructure.sqlite_store import SqliteStore
from tests.support import LEASE, make_request


def make_job(*, net_id, job_id="j1", **overrides):
    return Job(
        job_id=job_id, net_id=net_id, state=JobState.QUEUED, request=make_request(**overrides)
    )


@pytest.fixture
def net_id(store, mutex_pnml):
    return store.save_net(summary=pnml.summarize(pnml=mutex_pnml), pnml=mutex_pnml).summary.net_id


# ---- nets -----------------------------------------------------------------------------------


def test_net_round_trip_keeps_the_original_bytes(store, mutex_pnml, net_id):
    stored = store.load_net(net_id=net_id)
    assert stored.pnml == mutex_pnml
    assert stored.summary.places == 3


def test_saving_the_same_net_twice_keeps_one_copy(store, mutex_pnml, net_id):
    again = store.save_net(summary=pnml.summarize(pnml=mutex_pnml), pnml=mutex_pnml)
    assert again.summary.net_id == net_id


def test_unknown_net_raises(store):
    with pytest.raises(NotFoundError):
        store.load_net(net_id="nope")


# ---- jobs -----------------------------------------------------------------------------------


def test_job_round_trip(store, net_id):
    submission = store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    assert submission.created
    assert store.load_job(job_id="j1") == submission.job


def test_unknown_job_raises(store):
    with pytest.raises(NotFoundError):
        store.load_job(job_id="nope")


def test_equivalent_live_job_is_reused(store, net_id):
    first = store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"), lease_seconds=LEASE)
    second = store.create_or_get_job(job=make_job(net_id=net_id, job_id="b"), lease_seconds=LEASE)
    assert (first.created, second.created) == (True, False)
    assert second.job.job_id == first.job.job_id == "a"


def test_different_limits_make_a_different_job(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"), lease_seconds=LEASE)
    other = store.create_or_get_job(
        lease_seconds=LEASE,
        job=make_job(net_id=net_id, job_id="b", limits={"timeout_s": 5, "memory_mb": 128}),
    )
    assert other.created
    assert other.job.job_id == "b"


def test_a_different_net_makes_a_different_job(store, net_id):
    other_pnml = b'<pnml><net><place id="p"/><transition id="t"/></net></pnml>'
    other_net = store.save_net(summary=pnml.summarize(pnml=other_pnml), pnml=other_pnml)
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"), lease_seconds=LEASE)
    other = store.create_or_get_job(
        job=make_job(net_id=other_net.summary.net_id, job_id="b"), lease_seconds=LEASE
    )
    assert other.created


def test_cancelled_job_is_not_reused(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"), lease_seconds=LEASE)
    store.cancel(job_id="a")
    fresh = store.create_or_get_job(job=make_job(net_id=net_id, job_id="b"), lease_seconds=LEASE)
    assert fresh.created
    assert fresh.job.job_id == "b"


def test_mark_running_only_applies_to_queued_jobs(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    assert store.mark_running(job_id="j1", lease_seconds=LEASE) is True
    assert store.mark_running(job_id="j1", lease_seconds=LEASE) is False  # already running
    store.cancel(job_id="j1")
    assert store.mark_running(job_id="j1", lease_seconds=LEASE) is False


def test_finish_stores_results_and_marks_done(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.mark_running(job_id="j1", lease_seconds=LEASE)
    result = FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x", warnings=("w",))
    store.finish(job_id="j1", results=(result,))
    job = store.load_job(job_id="j1")
    assert job.state is JobState.DONE
    assert job.results == (result,)


def test_finish_does_not_resurrect_a_cancelled_job(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.cancel(job_id="j1")
    store.finish(job_id="j1", results=(FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x"),))
    job = store.load_job(job_id="j1")
    assert job.state is JobState.CANCELLED
    assert job.results == ()


def test_cancelling_a_finished_job_changes_nothing(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.mark_running(job_id="j1", lease_seconds=LEASE)
    store.finish(job_id="j1", results=())
    store.cancel(job_id="j1")
    assert store.load_job(job_id="j1").state is JobState.DONE


def test_recovery_interrupts_only_jobs_whose_lease_expired(store, net_id):
    # A negative lease is already expired: no clock to fake.
    store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="stale-queued", engine="dummy"), lease_seconds=-1
    )
    store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="stale-running", engine="itstools"), lease_seconds=-1
    )
    store.mark_running(job_id="stale-running", lease_seconds=-1)
    store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="alive", engine="tapaal"), lease_seconds=LEASE
    )
    store.mark_running(job_id="alive", lease_seconds=LEASE)
    store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="done", engine="smpt"), lease_seconds=-1
    )
    store.mark_running(job_id="done", lease_seconds=LEASE)
    store.finish(job_id="done", results=())

    assert store.recover_interrupted() == 2
    assert store.load_job(job_id="stale-queued").state is JobState.INTERRUPTED
    assert store.load_job(job_id="stale-running").state is JobState.INTERRUPTED
    assert store.load_job(job_id="alive").state is JobState.RUNNING
    assert store.load_job(job_id="done").state is JobState.DONE


def test_renewing_a_lease_keeps_a_job_out_of_recovery(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.mark_running(job_id="j1", lease_seconds=-1)
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is True
    assert store.recover_interrupted() == 0


def test_renewal_is_refused_once_the_job_is_not_running(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is False  # still queued
    store.mark_running(job_id="j1", lease_seconds=LEASE)
    store.cancel(job_id="j1")
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is False


def test_an_expired_job_cannot_be_finished_by_its_former_owner(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.mark_running(job_id="j1", lease_seconds=-1)
    store.recover_interrupted()
    store.finish(job_id="j1", results=(FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x"),))
    job = store.load_job(job_id="j1")
    assert job.state is JobState.INTERRUPTED
    assert job.results == ()


def test_an_interrupted_job_frees_its_idempotency_key(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="a"), lease_seconds=-1)
    store.recover_interrupted()
    again = store.create_or_get_job(job=make_job(net_id=net_id, job_id="b"), lease_seconds=LEASE)
    assert again.created is True


# ---- several processes sharing one database --------------------------------------------------


def test_only_one_of_two_processes_claims_a_job(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    claims = [
        store.mark_running(job_id="j1", lease_seconds=LEASE),
        other_process.mark_running(job_id="j1", lease_seconds=LEASE),
    ]
    assert sorted(claims) == [False, True]


def test_a_sweep_by_another_process_spares_live_jobs_and_finds_dead_ones(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="live"), lease_seconds=LEASE)
    store.mark_running(job_id="live", lease_seconds=LEASE)
    store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="dead", engine="itstools"), lease_seconds=-1
    )

    assert other_process.recover_interrupted() == 1
    assert store.load_job(job_id="live").state is JobState.RUNNING
    assert store.load_job(job_id="dead").state is JobState.INTERRUPTED


def test_cancelling_from_another_process_is_seen_by_the_owner(settings, store, net_id):
    other_process = SqliteStore(path=settings.database_path)
    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.mark_running(job_id="j1", lease_seconds=LEASE)
    other_process.cancel(job_id="j1")
    assert store.renew_lease(job_id="j1", lease_seconds=LEASE) is False


def test_data_survives_reopening_the_database(settings, net_id):
    reopened = SqliteStore(path=settings.database_path)
    assert reopened.load_net(net_id=net_id).summary.net_id == net_id
