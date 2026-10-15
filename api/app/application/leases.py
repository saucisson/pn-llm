"""Keep a job's lease alive while an engine runs, so other processes see its owner is alive."""

from __future__ import annotations

import threading
from types import TracebackType

from .ports import JobRepository

RENEWALS_PER_LEASE = 3


class LeaseKeeper:
    """Context manager that renews a running job's lease in a background thread.

    Renewal stops by itself when the job is no longer running (cancelled, or taken over after an
    expiry), so a lost job is never kept alive.
    """

    def __init__(self, *, jobs: JobRepository, job_id: str, lease_seconds: float) -> None:
        """Prepare the keeper; nothing runs until the ``with`` block is entered."""
        self._jobs = jobs
        self._job_id = job_id
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._renew_until_stopped, daemon=True)

    def _renew_until_stopped(self) -> None:
        interval = self._lease_seconds / RENEWALS_PER_LEASE
        while not self._stop.wait(timeout=interval):
            if not self._jobs.renew_lease(job_id=self._job_id, lease_seconds=self._lease_seconds):
                return

    def __enter__(self) -> LeaseKeeper:
        """Start renewing."""
        self._thread.start()
        return self

    def __exit__(  # noqa: PLR0917  (signature imposed by the context-manager protocol)
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop renewing and wait for the thread."""
        self._stop.set()
        self._thread.join()
