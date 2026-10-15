"""Pagination of deterministic lists: opaque offset cursors over immutable data."""

from __future__ import annotations

import base64
import binascii
from typing import Generic, TypeVar

from .contract import Page, PageRequest
from .errors import InvalidRequestError
from .models import DomainModel

T = TypeVar("T")


class Paged(DomainModel, Generic[T]):
    """One page of a list, with how much exists and how to get the rest."""

    items: tuple[T, ...]
    page: Page


def encode_cursor(*, offset: int) -> str:
    """Return the opaque cursor that resumes a list at ``offset``."""
    return base64.urlsafe_b64encode(f"o{offset}".encode()).decode().rstrip("=")


def decode_cursor(*, cursor: str) -> int:
    """Return the offset an opaque cursor stands for.

    Raises:
        InvalidRequestError: if the cursor was not produced by ``encode_cursor``.
    """
    try:
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not text.startswith("o"):
            raise ValueError(text)
        return max(int(text[1:]), 0)
    except (ValueError, binascii.Error) as exc:
        raise InvalidRequestError(f"Invalid cursor {cursor!r}") from exc


def paginate(*, items: tuple[T, ...], request: PageRequest) -> Paged[T]:
    """Return the page of ``items`` that ``request`` asks for.

    The list must be deterministic and unchanged between calls: nets are immutable, so it is.
    """
    offset = 0 if request.cursor is None else decode_cursor(cursor=request.cursor)
    chosen = items[offset : offset + request.limit]
    end = offset + len(chosen)
    next_cursor = encode_cursor(offset=end) if end < len(items) else None
    return Paged[T](
        items=chosen,
        page=Page(returned=len(chosen), total=len(items), next_cursor=next_cursor),
    )
