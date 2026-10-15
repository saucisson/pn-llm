"""The request and the answer of every reduction rule (ADR 0014, docs/json-contract.md)."""

from __future__ import annotations

from pydantic import Field, field_validator

from app.domain.contract import ElementRef
from app.domain.models import DomainModel
from app.domain.net_structure import NetStructure


class ReductionParameters(DomainModel):
    """Options common to every rule."""

    # Elements that must survive untouched: those a formula cites (CLAUDE.md, domain rule 3).
    protected: tuple[str, ...] = ()
    # Stop after this many applications of the rule; without it the rule runs to a fixpoint.
    max_applications: int | None = Field(default=None, ge=1)

    @field_validator("protected")
    @classmethod
    def _as_a_sorted_set(cls, protected: tuple[str, ...]) -> tuple[str, ...]:  # noqa: PLR0917 - pydantic calls validators positionally
        """Order and deduplicate the ids: the same set asked twice is the same request."""
        return tuple(sorted(set(protected)))


class MergedElements(DomainModel):
    """Elements replaced by one of them, which stays."""

    merged: tuple[ElementRef, ...]
    into: ElementRef


class TransitionExpansion(DomainModel):
    """What a firing of a transition of the reduced net stands for in the net it came from.

    A trace of the reduced net is lifted to the parent by replacing each firing with this sequence
    (docs/adding-a-reduction.md); transitions not listed stand for themselves.
    """

    transition: ElementRef
    original: tuple[ElementRef, ...]


class ReductionResult(DomainModel):
    """The answer of a reduction. The two ids are filled by the platform once the net is stored."""

    rule: str
    changed: bool
    parent_id: str | None = None
    new_net_id: str | None = None
    applications: int = Field(ge=0)
    removed: tuple[ElementRef, ...] = ()
    merged: tuple[MergedElements, ...] = ()
    expansions: tuple[TransitionExpansion, ...] = ()
    preserves: tuple[str, ...] = ()
    # Why nothing was done, when nothing was.
    note: str | None = None


class ReductionComputation(DomainModel):
    """What a reduction function returns: the answer and, if it changed the net, the new net."""

    result: ReductionResult
    reduced: NetStructure | None = None
