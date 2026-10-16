import pytest

from app.application.checks import CheckService
from app.application.experiment import ExperimentRunner
from app.application.inspection import InspectionService
from app.application.nets import NetService
from app.domain.experiment import ExperimentBudget, RunSpec
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from tests.support import LEASE, MUTEX_PNML, ScriptedEngines, make_analysis_tools


class ArcCounting(ScriptedEngines):
    """An engine whose answer depends on the net: TRUE while the net keeps its six arcs."""

    def run(self, *, engine, pnml, request, job_id):
        self.verdict = "TRUE" if pnml.count(b"<arc") >= 6 else "FALSE"
        return super().run(engine=engine, pnml=pnml, request=request, job_id=job_id)


def runner_over(*, store, engines):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    return nets, ExperimentRunner(
        nets=nets,
        checks=CheckService(nets=store, jobs=store, engines=engines, lease_seconds=LEASE),
        inspection=InspectionService(nets=store),
        analyses=make_analysis_tools(store=store, path=store._path),
    )


def spec(*, properties=20, **budget):
    return RunSpec(
        condition="B0",
        family="Mutex",
        repetition=0,
        seed="s1",
        budget=ExperimentBudget(
            max_properties=properties, check_timeout_s=5, mutants_per_operator=2, **budget
        ),
        git_commit="abc123",
    )


@pytest.fixture
def record(store):
    nets, runner = runner_over(store=store, engines=ArcCounting(trace_steps=("enter1",)))
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    return runner.run_baseline(spec=spec(), net_id=net_id)


def test_the_run_records_what_is_needed_to_reproduce_it(record):
    assert (record.spec.seed, record.spec.git_commit) == ("s1", "abc123")
    assert [(t.name, t.version) for t in record.tools] == [("scripted", "1.2.3")]
    assert {p.formula.origin for p in record.properties} == {"template"}
    assert {p.verdict.value for p in record.properties} == {"TRUE"}


def test_a_mutant_the_properties_tell_apart_is_killed_and_the_fault_found(record):
    removed = [m for m in record.mutants if m.operator == "remove_arc"]
    assert removed
    assert all(m.judgement.status == "killed" for m in removed)
    assert all(
        m.judgement.fault_found for m in removed
    )  # TRUE before, FALSE with a replaying trace
    assert removed[0].net_id
    assert removed[0].outcomes[0].replays_on_mutant is True


def test_a_mutant_nothing_distinguishes_survives_and_is_not_called_equivalent(record):
    added = [m for m in record.mutants if m.operator == "add_arc"]
    assert added
    assert all(m.judgement.status == "survived" for m in added)


def test_a_property_the_mutant_cannot_express_leaves_it_undecided_never_killed(record):
    removed = [m for m in record.mutants if m.operator == "remove_transition"]
    assert removed
    # The baseline cites every transition, so the mutant that lost one cannot be checked.
    assert all(m.judgement.status == "undecided" for m in removed)
    assert all(o.mutant.value == "ERROR" for m in removed for o in m.outcomes[1:] if o.mutant)


def test_the_score_counts_undecided_apart_and_the_mutants_are_the_same_for_the_same_seed(
    store, record
):
    score = record.mutation
    assert score.mutants == len(record.mutants)
    assert score.undecided >= 1
    assert score.killed + score.survived + score.undecided == score.mutants
    assert score.score is not None
    nets, runner = runner_over(store=store, engines=ArcCounting(trace_steps=("enter1",)))
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    again = runner.run_baseline(spec=spec(), net_id=net_id)
    assert [m.description for m in again.mutants] == [m.description for m in record.mutants]


def test_the_structure_decides_some_baseline_properties_and_the_measure_says_so(record):
    assert record.non_triviality.properties == len(record.properties)
    assert 0 < record.non_triviality.decided_by_structure < record.non_triviality.properties


def test_every_condition_gets_the_same_number_of_properties(store):
    nets, runner = runner_over(store=store, engines=ArcCounting(trace_steps=("enter1",)))
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    small = runner.run_baseline(spec=spec(properties=4), net_id=net_id)
    assert len(small.properties) == 4
    # A condition that offers more than the budget is cut to it, in the order it proposed.
    offered = tuple(p.formula for p in runner.run_baseline(spec=spec(), net_id=net_id).properties)
    cut = runner.measure(spec=spec(properties=3), net_id=net_id, formulas=offered)
    assert [p.formula.id for p in cut.properties] == [f.id for f in offered[:3]]
