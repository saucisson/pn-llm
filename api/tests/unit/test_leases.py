import time

from app.application.leases import LeaseKeeper


class FakeJobs:
    """Counts renewals; ``alive`` tells whether the job is still running."""

    def __init__(self, *, alive=True):
        self.alive = alive
        self.renewals = 0

    def renew_lease(self, *, job_id, lease_seconds):
        self.renewals += 1
        return self.alive


def wait_until(*, condition, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not condition():
        time.sleep(0.005)


def test_the_lease_is_renewed_while_the_block_runs():
    jobs = FakeJobs()
    with LeaseKeeper(jobs=jobs, job_id="j", lease_seconds=0.03, on_lost=lambda: None):
        wait_until(condition=lambda: jobs.renewals >= 2)
    assert jobs.renewals >= 2


def test_renewal_stops_when_the_block_ends():
    jobs = FakeJobs()
    with LeaseKeeper(jobs=jobs, job_id="j", lease_seconds=0.03, on_lost=lambda: None):
        wait_until(condition=lambda: jobs.renewals >= 1)
    count = jobs.renewals
    time.sleep(0.1)
    assert jobs.renewals == count


def test_renewal_stops_by_itself_when_the_job_was_lost_and_the_work_is_told_to_stop():
    jobs = FakeJobs(alive=False)
    lost = []
    with LeaseKeeper(jobs=jobs, job_id="j", lease_seconds=0.03, on_lost=lambda: lost.append(1)):
        wait_until(condition=lambda: jobs.renewals >= 1)
        time.sleep(0.15)
    assert jobs.renewals == 1
    assert lost == [1]


def test_a_live_job_never_triggers_the_lost_callback():
    jobs = FakeJobs()
    lost = []
    with LeaseKeeper(jobs=jobs, job_id="j", lease_seconds=0.03, on_lost=lambda: lost.append(1)):
        wait_until(condition=lambda: jobs.renewals >= 3)
    assert lost == []
