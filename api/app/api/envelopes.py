"""Build the shared result envelope around what a route computed."""

from __future__ import annotations

import time
from typing import TypeVar

from app import __version__
from app.domain.contract import Envelope, Page, ToolInfo

T = TypeVar("T")


def wrap[T](
    *, tool: str, net_id: str | None, started: float, data: T, page: Page | None = None
) -> Envelope[T]:
    """Return an ``ok`` envelope for ``data``; ``page`` is set when a list was cut short.

    ``started`` is a ``time.perf_counter()`` reading taken before the work.
    """
    truncated = page if page is not None and page.next_cursor is not None else None
    return Envelope[T](
        tool=ToolInfo(name=tool, version=__version__),
        net_id=net_id,
        status="ok",
        data=data,
        truncated=truncated,
        elapsed_s=time.perf_counter() - started,
    )
