import pytest

from app.application.checks import CheckService
from app.application.engines import EngineService
from app.application.nets import NetService
from app.domain import pnml
from app.domain.errors import InvalidRequestError, NotFoundError, PayloadTooLargeError
from app.domain.models import JobState, Verdict
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
    return NetService(nets=store, max_pnml_bytes=1_000_000)


@pytest.fixture
def checks(store, registry):
    return CheckService(nets=store, jobs=store, engines=registry, lease_seconds=LEASE)


@pytest.fixture
def net_id(nets, mutex_pnml):
    return nets.register(payload=mutex_pnml).net_id


# ---- NetService -----------------------------------------------------------------------------


def test_registering_the_same_content_twice_is_a_no_op(nets, mutex_pnml):
    assert nets.register(payload=mutex_pnml) == nets.register(payload=mutex_pnml)
    assert nets.get(net_id=pnml.summarize(pnml=mutex_pnml).net_id).places == 3


def test_oversized_payloads_are_rejected(store):
    small = NetService(nets=store, max_pnml_bytes=10)
    with pytest.raises(PayloadTooLargeError):
        small.register(payload=b"x" * 11)


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


def test_execute_runs_the_engine_and_stores_results(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    checks.execute(job_id=job_id)
    done = checks.get(job_id=job_id)
    assert done.state is JobState.DONE
    assert done.results[0].verdict is Verdict.UNKNOWN


def test_execute_skips_a_cancelled_job(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    checks.cancel(job_id=job_id)
    checks.execute(job_id=job_id)
    assert checks.get(job_id=job_id).state is JobState.CANCELLED


def test_execute_does_not_run_a_job_twice(checks, net_id):
    job_id = checks.submit(net_id=net_id, request=make_request()).job.job_id
    checks.execute(job_id=job_id)
    checks.execute(job_id=job_id)  # no longer queued: ignored
    assert checks.get(job_id=job_id).state is JobState.DONE


def test_an_engine_crash_becomes_an_error_verdict_not_a_stuck_job(store, net_id):
    class Crashing(EngineRegistry):
        def run(self, *, engine, pnml, request):
            raise RuntimeError("adapter bug")

    crashing = CheckService(
        nets=store,
        jobs=store,
        engines=Crashing(specs=DEFAULT_ENGINES, docker=NoDocker()),
        lease_seconds=LEASE,
    )
    job_id = crashing.submit(net_id=net_id, request=make_request()).job.job_id
    crashing.execute(job_id=job_id)
    done = crashing.get(job_id=job_id)
    assert done.state is JobState.DONE
    assert done.results[0].verdict is Verdict.ERROR
    assert "RuntimeError" in done.results[0].warnings[0]


def test_resubmitting_after_the_owner_died_creates_a_new_job(store, registry, net_id):
    # Simulates a crashed process: its job holds an expired lease and blocks the idempotency key.
    orphan = CheckService(nets=store, jobs=store, engines=registry, lease_seconds=-1)
    first = orphan.submit(net_id=net_id, request=make_request())
    healthy = CheckService(nets=store, jobs=store, engines=registry, lease_seconds=LEASE)

    second = healthy.submit(net_id=net_id, request=make_request())

    assert second.created is True
    assert second.job.job_id != first.job.job_id
    assert healthy.get(job_id=first.job.job_id).state is JobState.INTERRUPTED


def test_cancelling_an_unknown_job_raises(checks):
    with pytest.raises(NotFoundError):
        checks.cancel(job_id="nope")


# ---- EngineService --------------------------------------------------------------------------


def test_engine_service_lists_the_registry(registry):
    names = {engine.name for engine in EngineService(engines=registry).list_engines()}
    assert "dummy" in names
