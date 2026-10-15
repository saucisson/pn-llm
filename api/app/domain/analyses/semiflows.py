"""Minimal-support semiflows of an integer matrix: the core of P- and T-invariants.

A semiflow is a non-negative integer vector ``y`` with ``y^T C = 0``. The algorithm is the one of
Farkas (Martinez and Silva): rows are combined to cancel one column at a time, and only
minimal-support rows are kept. Its cost is exponential in the worst case, so it stops at a bound
and says so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import Field

from app.domain.models import DomainModel

type Row = tuple[tuple[int, ...], tuple[int, ...]]  # (what is left of the matrix, the combination)


class Semiflows(DomainModel):
    """Minimal-support semiflows, as one tuple of coefficients per row of the matrix."""

    flows: tuple[tuple[int, ...], ...]
    # False when the search stopped at its bound: the flows found are valid but there may be more.
    complete: bool
    rows: int = Field(ge=0)


def normalize(*, combination: tuple[int, ...], rest: tuple[int, ...]) -> Row:
    """Divide a row by the gcd of its coefficients, so equal flows are equal tuples."""
    divisor = math.gcd(*combination, *rest) or 1
    return tuple(v // divisor for v in rest), tuple(v // divisor for v in combination)


def minimal_semiflows(*, matrix: Sequence[Sequence[int]], max_rows: int) -> Semiflows:
    """Return the minimal-support semiflows of ``matrix`` (rows are the unknowns).

    ``max_rows`` bounds the working set; when it is exceeded the search stops and the result is
    marked incomplete. Rows with no non-zero coefficient at all (isolated unknowns) are flows by
    themselves.
    """
    count = len(matrix)
    work: list[Row] = [
        (tuple(row), tuple(1 if index == position else 0 for index in range(count)))
        for position, row in enumerate(matrix)
    ]
    columns = len(matrix[0]) if matrix else 0
    for column in range(columns):
        zero = [row for row in work if row[0][column] == 0]
        positive = [row for row in work if row[0][column] > 0]
        negative = [row for row in work if row[0][column] < 0]
        combined: list[Row] = []
        for plus in positive:
            for minus in negative:
                a, b = plus[0][column], -minus[0][column]
                scale = math.lcm(a, b)
                rest = tuple(
                    (scale // a) * x + (scale // b) * y
                    for x, y in zip(plus[0], minus[0], strict=True)
                )
                combination = tuple(
                    (scale // a) * x + (scale // b) * y
                    for x, y in zip(plus[1], minus[1], strict=True)
                )
                combined.append(normalize(combination=combination, rest=rest))
        # Keep the rows whose support (the unknowns they use) contains no other row's support.
        candidates = sorted({*zero, *combined}, key=lambda row: sum(1 for v in row[1] if v))
        kept: list[tuple[Row, frozenset[int]]] = []
        for candidate in candidates:
            support = frozenset(i for i, v in enumerate(candidate[1]) if v)
            if not any(other <= support for _, other in kept):
                kept.append((candidate, support))
        work = [row for row, _ in kept]
        if len(work) > max_rows:
            return Semiflows(flows=(), complete=False, rows=len(work))
    return Semiflows(flows=tuple(sorted({row[1] for row in work})), complete=True, rows=len(work))
