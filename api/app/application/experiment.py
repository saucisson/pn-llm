"""Measure a set of properties on a net and on its mutants (the judge of docs/evaluation.md).

The judge is deterministic: engines give the verdicts, a replay checks the counterexamples, the
structure says what is trivial. Where the properties come from (the baseline, a language model) does
not matter here; every condition goes through the same measurement under the same budget.
"""

from __future__ import annotations

from app.domain.baseline import BaselineBudget, BaselineFacts, baseline_properties
from app.domain.errors import DomainError
from app.domain.experiment import (
    MeasuredProperty,
    MutantRecord,
    RunRecord,
    RunSpec,
    ToolVersion,
)
from app.domain.formula import Formula
from app.domain.models import CheckRequest, DomainModel, FormulaResult, JobState, Limits, Verdict
from app.domain.mutation import mutants_of
from app.domain.mutation_score import PropertyOutcome, judge_mutant, score_family
from app.domain.nets import NetFormat
from app.domain.non_triviality import PropertyFindings, PropertySet, score_property_set
from app.domain.reductions.document import structure_to_document
from app.domain.replay import ReplayRequest

from .analysis_tools import AnalysisTools
from .checks import CheckService
from .inspection import InspectionService
from .nets import NetService


class CheckedSet(DomainModel):
    """The results of one check of all the properties, and the job to ask the traces of."""

    job_id: str | None
    results: tuple[FormulaResult, ...]


class ExperimentRunner:
    """Run the same measurement for every condition."""

    def __init__(
        self,
        *,
        nets: NetService,
        checks: CheckService,
        inspection: InspectionService,
        analyses: AnalysisTools,
    ) -> None:
        """Create the runner over the use cases it drives."""
        self._nets = nets
        self._checks = checks
        self._inspection = inspection
        self._analyses = analyses

    def run_baseline(self, *, spec: RunSpec, net_id: str) -> RunRecord:
        """Generate the properties of B0 for the net and measure them."""
        structure = self._inspection.structure(net_id=net_id)
        formulas = baseline_properties(
            structure=structure,
            facts=BaselineFacts(),
            budget=BaselineBudget(max_properties=spec.budget.max_properties),
        )
        return self.measure(spec=spec, net_id=net_id, formulas=formulas)

    def measure(self, *, spec: RunSpec, net_id: str, formulas: tuple[Formula, ...]) -> RunRecord:
        """Check the properties on the net, then on its mutants, and judge the set.

        The properties beyond the budget are not measured: every condition gets the same number.
        """
        kept = formulas[: spec.budget.max_properties]
        structure = self._inspection.structure(net_id=net_id)
        original = self.check_all(
            net_id=net_id, formulas=kept, timeout_s=spec.budget.check_timeout_s
        )
        findings = self._analyses.triviality(
            net_id=net_id, formulas=kept, is_cancelled=lambda: False
        )
        property_findings = tuple(
            PropertyFindings(property_id=item.formula_id, findings=item.findings)
            for item in findings
        )
        non_triviality = score_property_set(
            property_set=PropertySet(
                condition=spec.condition,
                family=spec.family,
                property_ids=tuple(f.id for f in kept),
                findings=property_findings,
            )
        )

        records: list[MutantRecord] = []
        for mutant in mutants_of(
            structure=structure,
            operators=spec.budget.operators,
            per_operator=spec.budget.mutants_per_operator,
            seed=spec.seed,
        ):
            mutant_net = self._nets.register(
                payload=structure_to_document(
                    structure=mutant.structure, source_id=f"mutant-of-{net_id}"
                )
                .model_dump_json()
                .encode(),
                format=NetFormat.JSON,
            ).stored.summary.net_id
            results = self.check_all(
                net_id=mutant_net, formulas=kept, timeout_s=spec.budget.check_timeout_s
            )
            outcomes = tuple(
                PropertyOutcome(
                    property_id=before.id,
                    original=before.verdict,
                    mutant=after.verdict,
                    replays_on_mutant=self.replays(net_id=mutant_net, checked=results, index=index),
                )
                for index, before in enumerate(original.results)
                for after in (results.results[index],)
            )
            records.append(
                MutantRecord(
                    description=mutant.description,
                    operator=mutant.operator,
                    net_id=mutant_net,
                    outcomes=outcomes,
                    judgement=judge_mutant(mutant_id=mutant.description, outcomes=outcomes),
                )
            )
        tools = sorted({(r.engine, r.engine_version) for r in original.results})
        return RunRecord(
            spec=spec,
            net_id=net_id,
            tools=tuple(ToolVersion(name=n, version=v) for n, v in tools),
            properties=tuple(
                MeasuredProperty(
                    formula=formula,
                    verdict=result.verdict,
                    engine=result.engine,
                    engine_version=result.engine_version,
                )
                for formula, result in zip(kept, original.results, strict=True)
            ),
            findings=property_findings,
            non_triviality=non_triviality,
            mutants=tuple(records),
            mutation=score_family(
                family=spec.family, judgements=tuple(r.judgement for r in records)
            ),
        )

    def check_all(
        self, *, net_id: str, formulas: tuple[Formula, ...], timeout_s: int
    ) -> CheckedSet:
        """Check every property on a net and wait for the verdicts.

        A property the net cannot express (it cites an element a mutant lost) or a check that did
        not finish is an ERROR for it: never a verdict, so the mutant stays undecided.
        """
        try:
            job = self._checks.submit(
                net_id=net_id,
                request=CheckRequest(formulas=formulas, limits=Limits(timeout_s=timeout_s)),
            ).job
            self._checks.drain()
            job = self._checks.get(job_id=job.job_id)
        except DomainError as error:
            return CheckedSet(
                job_id=None,
                results=tuple(
                    FormulaResult(
                        id=f.id,
                        verdict=Verdict.ERROR,
                        engine="platform",
                        engine_version="none",
                        warnings=(str(error),),
                    )
                    for f in formulas
                ),
            )
        by_id = {r.id: r for r in job.results}
        return CheckedSet(
            job_id=job.job_id if job.state is JobState.DONE else None,
            results=tuple(
                by_id.get(
                    f.id,
                    FormulaResult(
                        id=f.id,
                        verdict=Verdict.ERROR,
                        engine="platform",
                        engine_version="none",
                        warnings=(f"the check ended {job.state.value} without a result",),
                    ),
                )
                for f in formulas
            ),
        )

    def replays(self, *, net_id: str, checked: CheckedSet, index: int) -> bool | None:
        """Replay a counterexample on the net it was found on; None when there is none."""
        result = checked.results[index]
        if (
            checked.job_id is None
            or result.verdict is not Verdict.FALSE
            or result.trace_url is None
        ):
            return None
        trace = self._checks.trace(job_id=checked.job_id, result_index=index)
        return self._inspection.replay(
            net_id=net_id, request=ReplayRequest(steps=tuple(s.transition.id for s in trace.steps))
        ).valid
