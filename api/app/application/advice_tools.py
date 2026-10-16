"""The tools that advise on engines: which can check a property, and what to try after a failure.

The ranking comes from the selector (a trained model, contest history or a fixed order); the model
cannot override which engines are capable. The moves after a non-answer are suggestions: they never
turn a timeout or an UNKNOWN into a verdict (ADR 0006).
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.errors import InvalidRequestError
from app.domain.formula import Formula
from app.domain.models import Job, JobState
from app.domain.next_moves import ResultMoves, next_moves_for
from app.domain.tool_inputs import SelectToolsArguments

from .formulas import FormulaService
from .selection import SelectionRequest, SelectionService
from .tool_kit import Tool, ToolContext, ToolOutcome, answer, define_tool, failure, parse_formulas


class AdviceTools:
    """Engine selection and fallback advice, as tools."""

    def __init__(self, *, formulas: FormulaService, selection: SelectionService) -> None:
        """Create the tools over the formula parser and the selector."""
        self._formulas = formulas
        self._selection = selection

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
        )

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
