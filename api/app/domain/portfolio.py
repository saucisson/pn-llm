"""Merging the answers of several engines asked the same question (docs/equivalence.md).

When definitive verdicts disagree, something is wrong (a tool, an adapter, or a difference of
meaning), and which engine is right is not for the platform to guess: the result says UNKNOWN and
keeps all the evidence. The one exception is a counterexample the platform can replay itself: a
FALSE for an invariant that a replayed trace really violates is settled by the net, not by an
engine.
"""

from __future__ import annotations

from .engine_check import CheckOutcome
from .engine_contract import Trace
from .formula import CtlUnary, Expression, Formula, LtlUnary, Not, subexpressions
from .models import DomainModel, EngineAnswer, FormulaResult, Verdict
from .net_structure import NetStructure
from .replay import ReplayRequest, replay

DEFINITIVE = frozenset({Verdict.TRUE, Verdict.FALSE})
TEMPORAL = (LtlUnary, CtlUnary)


class EngineRun(DomainModel):
    """What one engine of the portfolio produced."""

    engine: str
    outcome: CheckOutcome


def invariant_of(*, formula: Formula) -> Expression | None:
    """Return ``phi`` if the formula says ``phi`` holds everywhere (AG or G), else None."""
    ast = formula.ast
    if isinstance(ast, CtlUnary | LtlUnary) and ast.op in {"AG", "G"}:
        inner = ast.arg
        if not any(
            isinstance(p.expression, TEMPORAL) for p in subexpressions(expression=inner, path="")
        ):
            return inner
    return None


def violates(*, formula: Formula, trace: Trace, structure: NetStructure) -> bool:
    """Tell whether a trace really ends in a marking that breaks an invariant, by replaying it."""
    invariant = invariant_of(formula=formula)
    if invariant is None:
        return False
    result = replay(
        structure=structure,
        request=ReplayRequest(
            steps=tuple(step.transition.id for step in trace.steps),
            state_formula=Not(arg=invariant),
        ),
    )
    return result.valid and result.state_formula_holds is True


def merge_outcomes(
    *, formulas: tuple[Formula, ...], runs: tuple[EngineRun, ...], structure: NetStructure
) -> CheckOutcome:
    """Merge what the engines answered into one result per formula.

    The verdict is the definitive one that the engines share, from the one that answered first;
    if none is definitive, the first engine's answer. If TRUE and FALSE both appear, it is
    UNKNOWN with ``agreement: contradiction``, unless a counterexample settles it by replay.
    Every engine's answer is kept in ``alternatives``.
    """
    results: list[FormulaResult] = []
    traces: list[Trace] = []
    for formula in formulas:
        answered = [
            (run, item, next((t for t in run.outcome.traces if t.formula_id == formula.id), None))
            for run in runs
            for item in run.outcome.results
            if item.id == formula.id
        ]
        alternatives = tuple(
            EngineAnswer(
                engine=run.engine,
                engine_version=item.engine_version,
                verdict=item.verdict,
                time_s=item.time_s,
                warnings=item.warnings,
                has_trace=trace is not None,
            )
            for run, item, trace in answered
        )
        definitive = [entry for entry in answered if entry[1].verdict in DEFINITIVE]
        verdicts = {entry[1].verdict for entry in definitive}
        if len(verdicts) > 1:
            settled = next(
                (
                    entry
                    for entry in definitive
                    if entry[1].verdict is Verdict.FALSE
                    and entry[2] is not None
                    and violates(formula=formula, trace=entry[2], structure=structure)
                ),
                None,
            )
            if settled is not None:
                _, item, trace = settled
                results.append(
                    item.model_copy(
                        update={
                            "agreement": "contradiction",
                            "arbitration": "counterexample_replayed",
                            "alternatives": alternatives,
                            "warnings": (*item.warnings, "engines_contradict"),
                        }
                    )
                )
                if trace is not None:
                    traces.append(trace)
            else:
                first = answered[0][1]
                results.append(
                    first.model_copy(
                        update={
                            "verdict": Verdict.UNKNOWN,
                            "engine": "+".join(a.engine for a in alternatives),
                            "engine_version": "various",
                            "agreement": "contradiction",
                            "alternatives": alternatives,
                            "warnings": ("engines_contradict",),
                            "trace_url": None,
                        }
                    )
                )
            continue
        if definitive:
            _, item, trace = min(definitive, key=lambda entry: entry[1].time_s)
            agreeing = len(definitive) > 1
        else:
            _, item, trace = answered[0]
            agreeing = False
        results.append(
            item.model_copy(
                update={
                    "agreement": "agree" if agreeing else "single",
                    "alternatives": alternatives if len(runs) > 1 else (),
                }
            )
        )
        if trace is not None:
            traces.append(trace)
    return CheckOutcome(results=tuple(results), traces=tuple(traces))
