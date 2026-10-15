import os
import signal
import subprocess
import sys
import time

import pytest

from app.application.checks import CheckService
from app.application.workers import WorkerPool
from app.domain.canonical import net_id_of
from app.domain.models import JobState
from app.domain.nets import summarize_document
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from tests.support import LEASE, MUTEX_DOCUMENT, make_formula, make_request


class NoDocker(DockerRunner):
    def image_present(self, *, image):
        return False


@pytest.fixture
def net_id(store):
    net = net_id_of(document=MUTEX_DOCUMENT)
    store.save_net(
        summary=summarize_document(document=MUTEX_DOCUMENT, net_id=net), document=MUTEX_DOCUMENT
    )
    return net


def service(*, store):
    registry = EngineRegistry(specs=DEFAULT_ENGINES, docker=NoDocker())
    return CheckService(nets=store, jobs=store, engines=registry, lease_seconds=LEASE)


def submit_many(*, checks, net_id, count):
    return [
        checks.submit(
            net_id=net_id,
            request=make_request(formulas=[make_formula(formula_id=f"f{index}")], engine="dummy"),
        ).job.job_id
        for index in range(count)
    ]


def wait_until(*, condition, seconds=15.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not condition():
        time.sleep(0.02)
    return condition()


def test_workers_run_every_job_exactly_once(store, net_id):
    checks = service(store=store)
    job_ids = submit_many(checks=checks, net_id=net_id, count=20)

    with WorkerPool(runners=(checks.run_next,), size=4, poll_seconds=0.01):
        assert wait_until(
            condition=lambda: all(checks.get(job_id=j).state is JobState.DONE for j in job_ids)
        )

    assert [len(checks.get(job_id=j).results) for j in job_ids] == [1] * 20


def test_a_pool_waits_for_the_job_in_progress_when_it_stops(store, net_id):
    checks = service(store=store)
    [job_id] = submit_many(checks=checks, net_id=net_id, count=1)
    with WorkerPool(runners=(checks.run_next,), size=1, poll_seconds=0.01):
        wait_until(condition=lambda: checks.get(job_id=job_id).state is not JobState.QUEUED)
    assert checks.get(job_id=job_id).state is JobState.DONE


def test_a_separate_worker_process_runs_the_jobs_of_the_database(settings, store, net_id):
    checks = service(store=store)
    job_ids = submit_many(checks=checks, net_id=net_id, count=3)
    environment = {
        **os.environ,
        "PNVERIF_DATABASE_PATH": str(settings.database_path),
        "PNVERIF_WORKER_POLL_SECONDS": "0.05",
    }
    worker = subprocess.Popen([sys.executable, "-m", "app.main"], env=environment)
    try:
        assert wait_until(
            condition=lambda: all(checks.get(job_id=j).state is JobState.DONE for j in job_ids),
            seconds=60,
        )
    finally:
        worker.send_signal(signal.SIGTERM)
        assert worker.wait(timeout=30) == 0
