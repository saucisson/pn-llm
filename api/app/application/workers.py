"""Worker threads that run queued check jobs and agent runs (ADR 0018).

The queues are database tables: a worker claims the oldest queued item with one atomic UPDATE, so
any number of workers in any number of processes can share them. API processes embed a few workers;
``python -m app.main`` starts a process that only runs workers.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType


class WorkerPool:
    """Context manager running ``size`` worker threads that poll the job queue."""

    def __init__(
        self, *, runners: tuple[Callable[[], bool], ...], size: int, poll_seconds: float
    ) -> None:
        """Prepare the pool; nothing runs until the ``with`` block is entered.

        Each runner does one unit of work if there is one (a check job, a session run) and says
        whether it did.
        """
        self._runners = runners
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._work, name=f"pnverif-worker-{index}", daemon=True)
            for index in range(size)
        ]

    def _work(self) -> None:
        while not self._stop.is_set():
            # Work back to back while there is some, then wait for the next poll.
            worked = False
            for runner in self._runners:
                worked = runner() or worked
            if not worked:
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
