"""Keep a lease alive while an engine runs, so other processes see its owner is alive."""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType

RENEWALS_PER_LEASE = 3


class LeaseKeeper:
    """Context manager that renews a running lease in a background thread.

    Renewal stops by itself when the job is no longer running (cancelled, or taken over after an
    expiry), so a lost job is never kept alive.
    """

    def __init__(
        self,
        *,
        renew: Callable[[], bool],
        lease_seconds: float,
        on_lost: Callable[[], None],
    ) -> None:
        """Prepare the keeper; nothing runs until the ``with`` block is entered.

        ``renew`` extends the lease and says whether the work still belongs to this process.
        ``on_lost`` is called once if it does not (the work was cancelled or taken over): what
        the lease protects must stop.
        """
        self._on_lost = on_lost
        self._renew = renew
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._renew_until_stopped, daemon=True)

    def _renew_until_stopped(self) -> None:
        interval = self._lease_seconds / RENEWALS_PER_LEASE
        while not self._stop.wait(timeout=interval):
            if not self._renew():
                self._on_lost()
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
