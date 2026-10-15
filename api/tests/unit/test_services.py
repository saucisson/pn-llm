import pytest

from app.application.checks import CheckService
from app.application.engines import EngineService
from app.application.nets import NetService
from app.domain.errors import InvalidRequestError, NotFoundError, PayloadTooLargeError
from app.domain.models import JobState, Verdict
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from tests.support import LEASE, make_request


class NoDocker(DockerRunner):
    def image_present(self, *, image):
        return False


@pytest.fixture
def registry():
    return EngineRegistry(specs=DEFAULT_ENGINES, docker=NoDocker())


@pytest.fixture
def nets(store):
    return NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())


@pytest.fixture
def checks(store, registry):
    return CheckService(nets=store, jobs=store, engines=registry, lease_seconds=LEASE)


@pytest.fixture
def net_id(nets, mutex_pnml):
    return nets.register(payload=mutex_pnml, format=NetFormat.PNML).stored.summary.net_id


# ---- NetService -----------------------------------------------------------------------------


def test_registering_the_same_content_twice_is_a_no_op(nets, mutex_pnml):
    first = nets.register(payload=mutex_pnml, format=NetFormat.PNML)
    again = nets.register(payload=mutex_pnml, format=NetFormat.PNML)
    assert (first.created, again.created) == (True, False)
    assert first.stored == again.stored
    assert nets.get(net_id=first.stored.summary.net_id).summary.places == 3


def test_oversized_payloads_are_rejected(store):
    small = NetService(nets=store, max_upload_bytes=10, limits=DocumentLimits())
    with pytest.raises(PayloadTooLargeError):
        small.register(payload=b"x" * 11, format=NetFormat.JSON)


def test_getting_an_unknown_net_raises(nets):
    with pytest.raises(NotFoundError):
        nets.get(net_id="nope")


# ---- CheckService ---------------------------------------------------------------------------


def test_submit_creates_then_reuses_the_job(checks, net_id):
    first = checks.submit(net_id=net_id, request=make_request())
    again = checks.submit(net_id=net_id, request=make_request())
    assert (first.created, again.created) == (True, False)
    assert again.job.job_id == first.job.job_id


def test_submit_rejects_an_unknown_net(checks):
    with pytest.raises(NotFoundError):
        checks.submit(net_id="nope", request=make_request())


def test_submit_rejects_an_unknown_engine(checks, net_id):
    with pytest.raises(InvalidRequestError):
        checks.submit(net_id=net_id, request=make_request(engine="nope"))


def test_submit_accepts_auto(checks, net_id):
    assert checks.submit(net_id=net_id, request=make_request(engine="auto")).created


def test_run_next_runs_the_engine_and_stores_results(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    assert checks.run_next() is True
    done = checks.get(job_id=job_id)
    assert done.state is JobState.DONE
    assert done.results[0].verdict is Verdict.UNKNOWN


def test_run_next_skips_a_cancelled_job(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    checks.cancel(job_id=job_id)
    assert checks.run_next() is False
    assert checks.get(job_id=job_id).state is JobState.CANCELLED


def test_a_job_is_not_run_twice(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    assert checks.run_next() is True
    assert checks.run_next() is False  # the queue is empty
    assert checks.get(job_id=job_id).state is JobState.DONE


def test_an_engine_crash_becomes_an_error_verdict_not_a_stuck_job(store, net_id):
    class Crashing(EngineRegistry):
        def run(self, *, engine, pnml, request, job_id):
            raise RuntimeError("adapter bug")

    crashing = CheckService(
        nets=store,
        jobs=store,
        engines=Crashing(specs=DEFAULT_ENGINES, docker=NoDocker()),
        lease_seconds=LEASE,
    )
    job_id = crashing.submit(net_id=net_id, request=make_request()).job.job_id
    crashing.run_next()
    done = crashing.get(job_id=job_id)
    assert done.state is JobState.DONE
    assert done.results[0].verdict is Verdict.ERROR
    assert "RuntimeError" in done.results[0].warnings[0]


def test_resubmitting_after_the_owner_died_creates_a_new_job(store, registry, net_id):
    # Simulates a crashed process: its running job holds an expired lease and blocks the key.
    orphan = CheckService(nets=store, jobs=store, engines=registry, lease_seconds=-1)
    first = orphan.submit(net_id=net_id, request=make_request())
    store.claim_next_job(lease_seconds=-1)
    healthy = CheckService(nets=store, jobs=store, engines=registry, lease_seconds=LEASE)

    second = healthy.submit(net_id=net_id, request=make_request())

    assert second.created is True
    assert second.job.job_id != first.job.job_id
    assert healthy.get(job_id=first.job.job_id).state is JobState.INTERRUPTED


def test_a_queued_job_waits_without_expiring(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    assert checks.recover_interrupted() == 0
    assert checks.get(job_id=job_id).state is JobState.QUEUED


def test_drain_runs_every_queued_job(checks, net_id):
    checks.submit(net_id=net_id, request=make_request(engine="dummy"))
    checks.submit(net_id=net_id, request=make_request(engine="itstools"))
    assert checks.drain() == 2
    assert checks.drain() == 0


def test_an_interrupted_job_can_be_retried(store, checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    store.claim_next_job(lease_seconds=-1)
    checks.recover_interrupted()
    assert checks.retry(job_id=job_id).state is JobState.QUEUED
    assert checks.drain() == 1
    assert checks.get(job_id=job_id).state is JobState.DONE


def test_only_an_interrupted_job_can_be_retried(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    with pytest.raises(InvalidRequestError, match="interrupted"):
        checks.retry(job_id=job_id)
    with pytest.raises(NotFoundError):
        checks.retry(job_id="nope")


def test_cancelling_an_unknown_job_raises(checks):
    with pytest.raises(NotFoundError):
        checks.cancel(job_id="nope")


# ---- EngineService --------------------------------------------------------------------------


def test_engine_service_lists_the_registry(registry):
    names = {engine.name for engine in EngineService(engines=registry).list_engines()}
    assert "dummy" in names


def test_old_finished_jobs_are_purged_through_the_service(checks, net_id, store):
    import sqlite3

    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    checks.run_next()
    conn = sqlite3.connect(store._path)
    conn.execute("UPDATE jobs SET updated_at=0")
    conn.commit()
    conn.close()
    assert checks.purge_old_jobs(retention_s=86_400) == 1
    with pytest.raises(NotFoundError):
        checks.get(job_id=job_id)
