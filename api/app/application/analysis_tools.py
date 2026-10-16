"""The analysis tools of the agent: structural facts about the net, from the operation runner.

Like a check, an analysis is asked of the platform, run by an engine and checked before the model
sees it. The agent works the queue itself while it waits, so it never depends on a free worker.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import JsonValue, ValidationError

from app.domain.analyses.conflict_sets import ConflictSetsParameters, ConflictSetsResult
from app.domain.analyses.connected_components import (
    ConnectedComponentsParameters,
    ConnectedComponentsResult,
)
from app.domain.analyses.dead_transitions import DeadTransitionsResult
from app.domain.analyses.net_class import NetClassResult
from app.domain.analyses.p_invariants import PInvariantsParameters, PInvariantsResult
from app.domain.analyses.place_bounds import PlaceBoundsParameters, PlaceBoundsResult
from app.domain.analyses.t_invariants import TInvariantsParameters, TInvariantsResult
from app.domain.analysis_summary import AnalysisResults, Unavailable, summarize_analyses
from app.domain.catalog import OPERATIONS, find_operation
from app.domain.contract import ToolInfo
from app.domain.formula import Formula
from app.domain.models import DomainModel, Limits
from app.domain.operations import (
    NoParameters,
    OperationRequest,
)
from app.domain.tool_inputs import AnalyzeArguments, NoArguments
from app.domain.triviality import StructuralFacts, Triviality, triviality_of

from .analysis_runner import AnalysisRunner
from .operations import OperationService
from .tool_kit import Tool, ToolContext, ToolOutcome, answer, define_tool, failure

# The digest asks for the cheap analyses with bounded searches; the heavy ones by name.
SUMMARY_TIMEOUT_S = 60
SUMMARY_MAX_ROWS = 5_000


class AnalysisData(DomainModel):
    """The answer of an analysis, with the tool that computed it."""

    operation: str
    tool: ToolInfo
    result: JsonValue


class FormulaTriviality(DomainModel):
    """The reasons a property says nothing, found from the structure of the net."""

    formula_id: str
    findings: tuple[Triviality, ...]


class AnalysisTools:
    """The tools that ask the platform for structural analyses."""

    def __init__(
        self, *, operations: OperationService, poll_seconds: float, summary_max_chars: int
    ) -> None:
        """Create the tools over the operation service."""
        self._operations = operations
        self._runner = AnalysisRunner(operations=operations, poll_seconds=poll_seconds)
        self._summary_max_chars = summary_max_chars

    def tools(self) -> tuple[Tool, ...]:
        """The two analysis tools."""
        names = ", ".join(op.name for op in OPERATIONS if op.kind == "analysis")
        return (
            define_tool(
                name="analysis_summary",
                description=(
                    "What the structure of a P/T net shows, in a few lines: its classes, "
                    "invariants (named), bounds, dead transitions, conflicts, components. Cheap "
                    "analyses only; what could not be computed is listed, never guessed. Use it "
                    "early to find out what to ask next."
                ),
                arguments=NoArguments,
                run=self.analysis_summary,
            ),
            define_tool(
                name="analyze",
                description=(
                    f"Run one structural analysis of a P/T net. Analyses: {names}. Facts come "
                    "from the structure and the initial marking; an analysis that stops at its "
                    "bound says so (complete: false) and what it lists is then not everything."
                ),
                arguments=AnalyzeArguments,
                run=self.analyze,
            ),
        )

    def analyze(
        self, *, context: ToolContext, arguments: AnalyzeArguments, is_cancelled: Callable[[], bool]
    ) -> ToolOutcome:
        """Run one analysis and report its result."""
        definition = find_operation(name=arguments.operation)
        if definition is None or definition.kind != "analysis":
            return failure(message=f"Unknown analysis {arguments.operation!r}")
        try:
            parameters = definition.parameters_model.model_validate(arguments.parameters)
        except ValidationError as exc:
            return failure(message=f"Invalid parameters: {exc.errors()[0]['msg']}")
        limits = Limits(timeout_s=SUMMARY_TIMEOUT_S)
        submission = self._operations.submit(
            net_id=context.session.net_id,
            operation=definition.name,
            request=OperationRequest(limits=limits, parameters=parameters),
        )
        run = self._runner.wait_for(
            run=submission.run, timeout_s=limits.timeout_s, is_cancelled=is_cancelled
        )
        if run is None:
            return failure(message="The analysis was cancelled or did not finish in time")
        if run.outcome is None or run.outcome.status != "ok":
            code = run.outcome.error.code if run.outcome and run.outcome.error else run.state.value
            return failure(message=f"The analysis gave no result ({code})")
        return answer(
            data=AnalysisData(
                operation=definition.name, tool=run.outcome.tool, result=run.outcome.result
            )
        )

    def analysis_summary(
        self, *, context: ToolContext, arguments: NoArguments, is_cancelled: Callable[[], bool]
    ) -> ToolOutcome:
        """Run the cheap analyses and report a digest that fits the budget."""
        net_class = self._runner.ask(
            net_id=context.session.net_id,
            name="net-class",
            parameters=NoParameters(),
            result_type=NetClassResult,
            is_cancelled=is_cancelled,
        )
        p_invariants = self._runner.ask(
            net_id=context.session.net_id,
            name="p-invariants",
            parameters=PInvariantsParameters(max_rows=SUMMARY_MAX_ROWS, max_invariants=20),
            result_type=PInvariantsResult,
            is_cancelled=is_cancelled,
        )
        t_invariants = self._runner.ask(
            net_id=context.session.net_id,
            name="t-invariants",
            parameters=TInvariantsParameters(max_rows=SUMMARY_MAX_ROWS, max_invariants=20),
            result_type=TInvariantsResult,
            is_cancelled=is_cancelled,
        )
        place_bounds = self._runner.ask(
            net_id=context.session.net_id,
            name="place-bounds",
            parameters=PlaceBoundsParameters(max_rows=SUMMARY_MAX_ROWS, max_places=1),
            result_type=PlaceBoundsResult,
            is_cancelled=is_cancelled,
        )
        dead = self._runner.ask(
            net_id=context.session.net_id,
            name="dead-transitions",
            parameters=NoParameters(),
            result_type=DeadTransitionsResult,
            is_cancelled=is_cancelled,
        )
        conflicts = self._runner.ask(
            net_id=context.session.net_id,
            name="conflict-sets",
            parameters=ConflictSetsParameters(max_groups=10),
            result_type=ConflictSetsResult,
            is_cancelled=is_cancelled,
        )
        components = self._runner.ask(
            net_id=context.session.net_id,
            name="connected-components",
            parameters=ConnectedComponentsParameters(max_components=10, max_elements=1),
            result_type=ConnectedComponentsResult,
            is_cancelled=is_cancelled,
        )
        asked = (net_class, p_invariants, t_invariants, place_bounds, dead, conflicts, components)
        results = AnalysisResults(
            net_class=net_class if isinstance(net_class, NetClassResult) else None,
            p_invariants=p_invariants if isinstance(p_invariants, PInvariantsResult) else None,
            t_invariants=t_invariants if isinstance(t_invariants, TInvariantsResult) else None,
            place_bounds=place_bounds if isinstance(place_bounds, PlaceBoundsResult) else None,
            dead_transitions=dead if isinstance(dead, DeadTransitionsResult) else None,
            conflict_sets=conflicts if isinstance(conflicts, ConflictSetsResult) else None,
            connected_components=(
                components if isinstance(components, ConnectedComponentsResult) else None
            ),
            unavailable=tuple(item for item in asked if isinstance(item, Unavailable)),
        )
        return answer(data=summarize_analyses(results=results, max_chars=self._summary_max_chars))

    def triviality(
        self, *, net_id: str, formulas: tuple[Formula, ...], is_cancelled: Callable[[], bool]
    ) -> tuple[FormulaTriviality, ...]:
        """Find the properties the structure of the net already decides, and say why.

        Nothing is found for a net the analyses do not cover (colored nets): an analysis that
        gave no result adds no fact.
        """
        bounds = self._runner.ask(
            net_id=net_id,
            name="place-bounds",
            parameters=PlaceBoundsParameters(max_rows=SUMMARY_MAX_ROWS, max_places=100_000),
            result_type=PlaceBoundsResult,
            is_cancelled=is_cancelled,
        )
        invariants = self._runner.ask(
            net_id=net_id,
            name="p-invariants",
            parameters=PInvariantsParameters(max_rows=SUMMARY_MAX_ROWS),
            result_type=PInvariantsResult,
            is_cancelled=is_cancelled,
        )
        dead = self._runner.ask(
            net_id=net_id,
            name="dead-transitions",
            parameters=NoParameters(),
            result_type=DeadTransitionsResult,
            is_cancelled=is_cancelled,
        )
        facts = StructuralFacts(
            bounds=bounds if isinstance(bounds, PlaceBoundsResult) else None,
            invariants=invariants if isinstance(invariants, PInvariantsResult) else None,
            dead=dead if isinstance(dead, DeadTransitionsResult) else None,
        )
        found = tuple(
            FormulaTriviality(formula_id=f.id, findings=triviality_of(formula=f, facts=facts))
            for f in formulas
        )
        return tuple(item for item in found if item.findings)
