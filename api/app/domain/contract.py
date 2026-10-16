"""Shared JSON contract: result envelope, element references, bounds, markings and pages.

Reference: docs/json-contract.md (ADR 0013). Every tool result reuses these shapes.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from .models import DomainModel

SCHEMA_VERSION: Literal["1.0"] = "1.0"
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500

T = TypeVar("T")


class ElementRef(DomainModel):
    """Cite a place or a transition by id; the name is kept exactly as in the net."""

    id: str
    name: str | None = None
    kind: Literal["place", "transition"]


class Assignment(DomainModel):
    """The color a variable takes in a binding of a colored transition."""

    variable: str
    color: str


class MarkingEntry(DomainModel):
    """A place holding at least one token."""

    place: ElementRef
    tokens: int = Field(ge=1)


class Marking(DomainModel):
    """A sparse marking: places holding no token are omitted; entries are sorted by place id."""

    entries: tuple[MarkingEntry, ...] = ()

    @field_validator("entries")
    @classmethod
    def _sorted_by_place_id(  # noqa: PLR0917 - pydantic calls validators positionally
        cls, entries: tuple[MarkingEntry, ...]
    ) -> tuple[MarkingEntry, ...]:
        """Sort entries so that the same marking always serializes to the same JSON."""
        return tuple(sorted(entries, key=lambda entry: entry.place.id))


class FiniteBound(DomainModel):
    """A bound known to be a number."""

    kind: Literal["finite"] = "finite"
    value: int = Field(ge=0)


class UnboundedBound(DomainModel):
    """A place proven unbounded."""

    kind: Literal["unbounded"] = "unbounded"


class UnknownBound(DomainModel):
    """The tool could not decide; never encoded as null or a magic number."""

    kind: Literal["unknown"] = "unknown"


Bound = Annotated[FiniteBound | UnboundedBound | UnknownBound, Field(discriminator="kind")]


class PageRequest(DomainModel):
    """Pagination parameters of a list request."""

    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
    cursor: str | None = None


class Page(DomainModel):
    """Says how much of a list was returned, how much exists, and how to get the rest."""

    returned: int = Field(ge=0)
    total: int = Field(ge=0)
    next_cursor: str | None = None


class ToolInfo(DomainModel):
    """The tool and pinned version that produced a result."""

    name: str
    version: str


class ErrorInfo(DomainModel):
    """Expected failure of a tool (timeout, out of memory, ...), reported in the envelope."""

    code: str
    message: str


class Envelope[T](DomainModel):
    """Result of every analysis, inspection, reduction and check, around its own ``data``."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    tool: ToolInfo
    net_id: str | None = None
    status: Literal["ok", "partial", "failed"]
    data: T | None = None
    warnings: tuple[str, ...] = ()
    truncated: Page | None = None
    error: ErrorInfo | None = None
    elapsed_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _failed_means_error_and_no_data(self) -> Envelope[T]:
        """Reject envelopes whose status contradicts their data and error."""
        if self.status == "failed":
            if self.data is not None or self.error is None:
                message = "a failed envelope has an error and no data"
                raise ValueError(message)
        elif self.error is not None or self.data is None:
            message = "an ok or partial envelope has data and no error"
            raise ValueError(message)
        return self
