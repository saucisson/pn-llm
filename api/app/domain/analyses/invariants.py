"""What the invariant analyses share: their options and the weighted elements they list."""

from __future__ import annotations

from pydantic import Field

from app.domain.contract import ElementRef
from app.domain.models import DomainModel


class SemiflowParameters(DomainModel):
    """Options of a search for minimal-support invariants."""

    # Stop the search when the working set grows beyond this many rows (the result then says so).
    max_rows: int = Field(default=20_000, ge=1, le=1_000_000)
    # At most this many invariants are listed; the total is always given.
    max_invariants: int = Field(default=200, ge=1, le=10_000)


class WeightedElement(DomainModel):
    """An element of an invariant and its weight."""

    element: ElementRef
    weight: int = Field(ge=1)
