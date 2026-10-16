"""The tools that advise on engines and interpret their answers.

They say which engines can check a property, what to try after a failure, and record how the
model reads a counterexample.

The ranking comes from the selector (a trained model, contest history or a fixed order); the model
cannot override which engines are capable. The moves after a non-answer are suggestions: they never
turn a timeout or an UNKNOWN into a verdict (ADR 0006).
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.errors import InvalidRequestError
from app.domain.formula import Formula
from app.domain.models import Job, JobState, Verdict
from app.domain.next_moves import ResultMoves, next_moves_for
from app.domain.sessions import CounterexampleClassified
from app.domain.tool_inputs import ClassifyCounterexampleArguments, SelectToolsArguments

from .checks import CheckService
from .formulas import FormulaService
from .selection import SelectionRequest, SelectionService
from .tool_kit import Tool, ToolContext, ToolOutcome, answer, define_tool, failure, parse_formulas


class AdviceTools:
    """Engine selection and fallback advice, as tools."""

    def __init__(
        self, *, formulas: FormulaService, selection: SelectionService, checks: CheckService
    ) -> None:
        """Create the tools over the formula parser and the selector."""
        self._formulas = formulas
        self._selection = selection
        self._checks = checks

    def tools(self) -> tuple[Tool, ...]:
        """The tools of this family."""
        return (
            define_tool(
                name="select_tools",
                description=(
                    "Which engines can check these properties on this net, best first, with the "
                    "evidence for the ranking (chance of an answer and expected time when known). "
                    "Use it to choose an engine or to see what else can be tried after a TIMEOUT, "
                    "OOM or UNKNOWN. An engine absent from the list cannot check these properties. "
                    "Runs no engine."
                ),
                arguments=SelectToolsArguments,
                run=self.select_tools,
            ),
            define_tool(
                name="classify_counterexample",
                description=(
                    "Record how you read the counterexample of a FALSE result: a bug of the model, "
                    "a property that asks too much, or behaviour that is meant to be possible. "
                    "This is your interpretation, kept in the report as such; it changes no "
                    "verdict. Look at the trace (get_trace) and replay it before classifying."
                ),
                arguments=ClassifyCounterexampleArguments,
                run=self.classify_counterexample,
            ),
        )

    def classify_counterexample(
        self,
        *,
        context: ToolContext,
        arguments: ClassifyCounterexampleArguments,
        is_cancelled: Callable[[], bool],
    ) -> ToolOutcome:
        """Record the model's reading of a counterexample, if the result has one on this net."""
        job = self._checks.get(job_id=arguments.job_id)
        if job.net_id != context.session.net_id:
            return failure(message="That job belongs to another net")
        if arguments.result_index >= len(job.results):
            return failure(message="That job has no such result")
        result = job.results[arguments.result_index]
        if result.verdict is not Verdict.FALSE or result.trace_url is None:
            return failure(
                message=(
                    f"Result {arguments.result_index} is {result.verdict.value} without a "
                    "counterexample: there is nothing to classify"
                )
            )
        event = CounterexampleClassified(
            job_id=arguments.job_id,
            result_index=arguments.result_index,
            formula_id=result.id,
            classification=arguments.classification,
            explanation=arguments.explanation,
        )
        outcome = answer(data={"recorded": arguments.classification, "formula_id": result.id})
        return outcome.model_copy(update={"events": (event,)})

    def select_tools(
        self,
        *,
        context: ToolContext,
        arguments: SelectToolsArguments,
        is_cancelled: Callable[[], bool],
    ) -> ToolOutcome:
        """Rank the engines able to check the properties."""
        parsed = parse_formulas(
            formulas=self._formulas, net_id=context.session.net_id, items=arguments.formulas
        )
        if parsed.error is not None:
            return failure(message=parsed.error)
        selection = self._selection.select(
            request=SelectionRequest(net_id=context.session.net_id, formulas=parsed.formulas)
        )
        return answer(data=selection)

    def moves_after(
        self, *, net_id: str, formulas: tuple[Formula, ...], job: Job
    ) -> tuple[ResultMoves, ...]:
        """Propose what to try for each formula of a finished job that got no answer."""
        if job.state is not JobState.DONE:
            return ()
        by_id = {formula.id: formula for formula in formulas}
        found: list[ResultMoves] = []
        for result in job.results:
            formula = by_id.get(result.id)
            if formula is None:
                continue
            try:
                ranked = self._selection.select(
                    request=SelectionRequest(
                        net_id=net_id, formulas=(formula,), limits=job.request.limits
                    )
                ).ranked
            except InvalidRequestError:
                ranked = ()
            tried = {result.engine, *(a.engine for a in result.alternatives)}
            moves = next_moves_for(
                result=result,
                untried_engines=tuple(r.engine for r in ranked if r.engine not in tried),
                reduced=job.request.reduce,
                timeout_s=job.request.limits.timeout_s,
            )
            if moves is not None:
                found.append(moves)
        return tuple(found)
