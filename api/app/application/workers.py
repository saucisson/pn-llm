"""Worker threads that run the queued jobs (docs/architecture.md, "Several processes").

The queue is the ``jobs`` table: a worker claims the oldest queued job with one atomic UPDATE, so
any number of workers in any number of processes can share it. API processes embed a few workers;
``python -m app.main`` starts a process that only runs workers.
"""

from __future__ import annotations

import threading
from types import TracebackType

from .checks import CheckService


class WorkerPool:
    """Context manager running ``size`` worker threads that poll the job queue."""

    def __init__(self, *, checks: CheckService, size: int, poll_seconds: float) -> None:
        """Prepare the pool; nothing runs until the ``with`` block is entered."""
        self._checks = checks
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._work, name=f"pnverif-worker-{index}", daemon=True)
            for index in range(size)
        ]

    def _work(self) -> None:
        while not self._stop.is_set():
            # Run jobs back to back while there are some, then wait for the next poll.
            if not self._checks.run_next():
                self._stop.wait(timeout=self._poll_seconds)

    def __enter__(self) -> WorkerPool:
        """Start the threads."""
        for thread in self._threads:
            thread.start()
        return self

    def __exit__(  # noqa: PLR0917  (signature imposed by the context-manager protocol)
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Ask the threads to stop after their current job, and wait for them."""
        self._stop.set()
        for thread in self._threads:
            thread.join()
