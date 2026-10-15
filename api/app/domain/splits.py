"""Splits of the model families into development folds and a held-out test set (docs/evaluation.md).

The unit of evaluation is the family, never the instance: all instances of a scalable model go
to the same side, so a tool or prompt tuned on one size is never tested on another size of the
same model.
"""

from __future__ import annotations

import hashlib
import math
from typing import Literal

from pydantic import Field

from .errors import InvalidRequestError
from .models import DomainModel

Role = Literal["dev", "test"]


class FamilyAssignment(DomainModel):
    """Where a family goes: a development fold, or the held-out test set (no fold)."""

    family: str
    role: Role
    fold: int | None = None


class Split(DomainModel):
    """A frozen assignment of families. Once stored under a name it is never changed."""

    name: str = Field(min_length=1)
    seed: str
    folds: int = Field(ge=2)
    test_fraction: float = Field(ge=0, lt=1)
    assignments: tuple[FamilyAssignment, ...]


def rank_of(*, seed: str, purpose: str, family: str) -> str:
    """Return a seeded pseudo-random sort key for a family: same inputs, same key, anywhere."""
    return hashlib.sha256(f"{seed}|{purpose}|{family}".encode()).hexdigest()


def make_split(
    *, name: str, seed: str, folds: int, test_fraction: float, families: tuple[str, ...]
) -> Split:
    """Assign every family to the test set or to one development fold, reproducibly.

    The test set takes the first ``ceil(test_fraction * n)`` families by a seeded order; the
    others are dealt round-robin to the folds in another seeded order, so fold sizes differ by
    at most one.

    Raises:
        InvalidRequestError: if there are fewer development families than folds.
    """
    distinct = tuple(sorted(set(families)))
    by_test_rank = sorted(distinct, key=lambda f: rank_of(seed=seed, purpose="test", family=f))
    test_count = math.ceil(test_fraction * len(distinct))
    held_out = set(by_test_rank[:test_count])
    dev = sorted(
        (f for f in distinct if f not in held_out),
        key=lambda f: rank_of(seed=seed, purpose="fold", family=f),
    )
    if len(dev) < folds:
        raise InvalidRequestError(f"{len(dev)} development families cannot fill {folds} folds")
    folds_of = {family: index % folds for index, family in enumerate(dev)}
    return Split(
        name=name,
        seed=seed,
        folds=folds,
        test_fraction=test_fraction,
        assignments=tuple(
            FamilyAssignment(family=f, role="test")
            if f in held_out
            else FamilyAssignment(family=f, role="dev", fold=folds_of[f])
            for f in distinct
        ),
    )
