"""What to try after an engine did not answer, as a short list the model can choose from.

An engine that times out, runs out of memory, says UNKNOWN or fails has told nothing about the
property (ADR 0006). The moves below only change the question or the means: they never turn the
non-answer into a verdict. The model decides which one to take; the platform's capability checks
still apply to whatever it asks next.
"""

from __future__ import annotations

from typing import Literal

from .models import DomainModel, FormulaResult, Verdict

NON_ANSWERS = frozenset({Verdict.UNKNOWN, Verdict.TIMEOUT, Verdict.OOM, Verdict.ERROR})
MAX_TOOL_TIMEOUT_S = 600


class NextMove(DomainModel):
    """One thing worth trying after a non-answer, and why."""

    kind: Literal[
        "other_engine", "reduce_first", "longer_timeout", "simpler_property", "weaker_property"
    ]
    detail: str


class ResultMoves(DomainModel):
    """The moves proposed for one formula that got no answer."""

    formula_id: str
    verdict: Verdict
    engine: str
    moves: tuple[NextMove, ...]


def next_moves_for(
    *, result: FormulaResult, untried_engines: tuple[str, ...], reduced: bool, timeout_s: int
) -> ResultMoves | None:
    """Return the moves after a non-answer, or None when the result is an answer."""
    if result.verdict not in NON_ANSWERS or result.agreement == "contradiction":
        return None
    moves: list[NextMove] = []
    if untried_engines:
        moves.append(
            NextMove(
                kind="other_engine",
                detail=f"ask {', '.join(untried_engines)}: can check it, not tried yet",
            )
        )
    if result.verdict is Verdict.ERROR:
        return ResultMoves(
            formula_id=result.id, verdict=result.verdict, engine=result.engine, moves=tuple(moves)
        )
    if not reduced:
        moves.append(
            NextMove(kind="reduce_first", detail="run again with the engine's reductions enabled")
        )
    if result.verdict is Verdict.TIMEOUT and timeout_s < MAX_TOOL_TIMEOUT_S:
        moves.append(
            NextMove(
                kind="longer_timeout",
                detail=f"allow more than {timeout_s} s (at most {MAX_TOOL_TIMEOUT_S} s)",
            )
        )
    moves.append(
        NextMove(
            kind="simpler_property",
            detail="check a property that mentions fewer places or one operator less",
        )
    )
    moves.append(
        NextMove(
            kind="weaker_property",
            detail="check a weaker property (a bound instead of an exact count, one case "
            "instead of all); a result on it does not settle the original one",
        )
    )
    return ResultMoves(
        formula_id=result.id, verdict=result.verdict, engine=result.engine, moves=tuple(moves)
    )
