import sqlite3
import threading
import time

import pytest

from app.domain.canonical import net_id_of
from app.domain.models import FormulaResult, Job, JobState, Verdict
from app.domain.nets import summarize_document
from app.infrastructure.sqlite_backup import backup_database, restore_database
from app.infrastructure.sqlite_migrations import StoreMigrationError
from app.infrastructure.sqlite_store import SqliteStore
from tests.support import LEASE, MUTEX_DOCUMENT, make_request


def make_job(*, net_id, job_id="j1", **overrides):
    return Job(
        job_id=job_id, net_id=net_id, state=JobState.QUEUED, request=make_request(**overrides)
    )


@pytest.fixture
def net_id(store):
    document = MUTEX_DOCUMENT
    net = net_id_of(document=document)
    store.save_net(summary=summarize_document(document=document, net_id=net), document=document)
    return net


def finish_job(*, store, net_id, job_id, age_s):
    store.create_or_get_job(
        job=make_job(net_id=net_id, job_id=job_id, engine=job_id), lease_seconds=LEASE
    )
    store.mark_running(job_id=job_id, lease_seconds=LEASE)
    store.finish(
        job_id=job_id,
        results=(FormulaResult(id="f1", verdict=Verdict.TRUE, engine="x"),),
        traces=(),
    )
    conn = sqlite3.connect(store._path)
    conn.execute("UPDATE jobs SET updated_at=? WHERE job_id=?", (time.time() - age_s, job_id))
    conn.commit()
    conn.close()


# ---- retention ------------------------------------------------------------------------------


def test_old_finished_jobs_are_purged_and_recent_ones_kept(store, net_id):
    finish_job(store=store, net_id=net_id, job_id="old", age_s=10 * 86_400)
    finish_job(store=store, net_id=net_id, job_id="recent", age_s=60)
    assert store.purge_finished_jobs(older_than_s=86_400) == 1
    with pytest.raises(Exception, match="Unknown job"):
        store.load_job(job_id="old")
    assert store.load_job(job_id="recent").state is JobState.DONE


def test_live_jobs_and_nets_are_never_purged(store, net_id):
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="queued"), lease_seconds=LEASE)
    conn = sqlite3.connect(store._path)
    conn.execute("UPDATE jobs SET updated_at=0")
    conn.commit()
    conn.close()
    assert store.purge_finished_jobs(older_than_s=1) == 0
    assert store.load_job(job_id="queued").state is JobState.QUEUED
    assert store.load_net(net_id=net_id).summary.net_id == net_id


def test_purging_a_job_removes_its_traces(store, net_id):
    from app.domain.contract import Marking
    from app.domain.engine_contract import Trace

    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    store.mark_running(job_id="j1", lease_seconds=LEASE)
    trace = Trace(formula_id="f1", net_id=net_id, initial_marking=Marking(), steps=())
    store.finish(job_id="j1", results=(), traces=(trace,))
    assert store.load_trace(job_id="j1", formula_id="f1").formula_id == "f1"
    conn = sqlite3.connect(store._path)
    conn.execute("UPDATE jobs SET updated_at=0")
    conn.commit()
    conn.close()
    store.purge_finished_jobs(older_than_s=1)
    conn = sqlite3.connect(store._path)
    assert conn.execute("SELECT count(*) FROM traces").fetchone()[0] == 0


# ---- backup and restore ---------------------------------------------------------------------


def test_a_backup_can_be_restored_after_the_data_was_lost(settings, store, net_id, tmp_path):
    finish_job(store=store, net_id=net_id, job_id="kept", age_s=0)
    backup = tmp_path / "backups" / "b.sqlite"
    backup_database(source=settings.database_path, target=backup)

    store.purge_finished_jobs(older_than_s=-1)  # "disaster": every finished job is gone
    with pytest.raises(Exception, match="Unknown job"):
        store.load_job(job_id="kept")

    restore_database(backup=backup, target=settings.database_path)
    restored = SqliteStore(path=settings.database_path)
    assert restored.load_job(job_id="kept").state is JobState.DONE
    assert restored.load_net(net_id=net_id).summary.places == 3


def test_a_backup_never_overwrites_another(settings, store, tmp_path):
    backup = tmp_path / "b.sqlite"
    backup_database(source=settings.database_path, target=backup)
    with pytest.raises(FileExistsError):
        backup_database(source=settings.database_path, target=backup)


def test_a_damaged_or_newer_backup_is_refused_and_the_database_kept(
    settings, store, net_id, tmp_path
):
    damaged = tmp_path / "damaged.sqlite"
    damaged.write_bytes(b"this is not a database" * 100)
    with pytest.raises(Exception, match=r"not a database|damaged|malformed"):
        restore_database(backup=damaged, target=settings.database_path)

    future = tmp_path / "future.sqlite"
    conn = sqlite3.connect(future)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(StoreMigrationError, match="too new"):
        restore_database(backup=future, target=settings.database_path)
    assert store.load_net(net_id=net_id).summary.places == 3


# ---- the retry path of job creation (#28) ---------------------------------------------------


class InterferingStore(SqliteStore):
    """Cancels the live job that blocks an insert, between the failed insert and the lookup."""

    def __init__(self, *, path, blocking_job_id):
        super().__init__(path=path)
        self.blocking_job_id = blocking_job_id
        self.armed = False
        self.lookups = 0

    def _connection(self):
        if self.armed:
            self.lookups += 1
            if self.lookups == 2:  # the second connection of a failed insert is the lookup
                self.armed = False
                SqliteStore.cancel(self, job_id=self.blocking_job_id)
        return super()._connection()


def test_the_insert_is_retried_when_the_blocking_job_finishes_in_between(settings, net_id):
    store = InterferingStore(path=settings.database_path, blocking_job_id="blocker")
    store.create_or_get_job(job=make_job(net_id=net_id, job_id="blocker"), lease_seconds=LEASE)
    store.armed = True

    submission = store.create_or_get_job(
        job=make_job(net_id=net_id, job_id="second"), lease_seconds=LEASE
    )

    assert submission.created is True
    assert submission.job.job_id == "second"
    assert store.load_job(job_id="blocker").state is JobState.CANCELLED


def test_two_threads_submitting_the_same_check_get_one_job(settings, net_id):
    store = SqliteStore(path=settings.database_path)
    outcomes = []

    def submit(name):
        outcomes.append(
            store.create_or_get_job(job=make_job(net_id=net_id, job_id=name), lease_seconds=LEASE)
        )

    threads = [threading.Thread(target=submit, args=(f"t{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(outcome.created for outcome in outcomes) == 1
    assert len({outcome.job.job_id for outcome in outcomes}) == 1


def test_a_missing_trace_is_not_found(store, net_id):
    from app.domain.errors import NotFoundError

    store.create_or_get_job(job=make_job(net_id=net_id), lease_seconds=LEASE)
    with pytest.raises(NotFoundError, match="No trace"):
        store.load_trace(job_id="j1", formula_id="f1")
