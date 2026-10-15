import pytest

from app.application.checks import CheckService
from app.application.nets import NetService
from app.application.operations import OperationService
from app.application.traces import TraceService
from app.domain.contract import ElementRef, Marking
from app.domain.engine_contract import Trace, TraceStep
from app.domain.errors import InvalidRequestError
from app.domain.formula_text import formula_from_text
from app.domain.lifting import lift_trace
from app.domain.models import CheckRequest
from app.domain.net_structure import build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from app.domain.operations import Lineage, LineageExpansion, OperationRequest
from app.domain.pnml_export import render_pnml
from app.domain.reductions.document import structure_to_document
from app.domain.reductions.result import ReductionParameters
from app.infrastructure.sqlite_operations import SqliteOperations
from tests.reduction_oracle import structure_of
from tests.support import LEASE, InProcessNative, ScriptedEngines

LOOP = structure_of(
    places=["a", "mid", "q"],
    transitions=["x", "t", "y"],
    arcs=[("a", "x"), ("x", "mid"), ("mid", "t"), ("t", "q"), ("q", "y"), ("y", "a")],
    marking={"a": 1},
)


def trace_of(*steps, loop_start=None, net_id="reduced"):
    return Trace(
        formula_id="f1",
        net_id=net_id,
        initial_marking=Marking(entries=()),
        steps=tuple(
            TraceStep(transition=ElementRef(id=s, name=s, kind="transition")) for s in steps
        ),
        loop_start=loop_start,
    )


def link(**expansions):
    return Lineage(
        net_id="reduced",
        parent_id="original",
        rule="r",
        expansions=tuple(LineageExpansion(transition=k, original=v) for k, v in expansions.items()),
    )


def test_each_firing_is_replaced_by_the_sequence_it_stands_for():
    lifted = lift_trace(
        trace=trace_of("x", "y", "x"),
        chain=(link(x=("x", "t")),),
        root=build_structure(
            document=structure_to_document(structure=LOOP, source_id="n"), net_id="original"
        ),
    )
    assert [s.transition.id for s in lifted.steps] == ["x", "t", "y", "x", "t"]
    assert lifted.net_id == "original"
    assert [(e.place.id, e.tokens) for e in lifted.initial_marking.entries] == [("a", 1)]


def test_the_loop_start_follows_the_steps_before_it():
    root = build_structure(
        document=structure_to_document(structure=LOOP, source_id="n"), net_id="original"
    )
    lifted = lift_trace(
        trace=trace_of("x", "y", "x", loop_start=1), chain=(link(x=("x", "t")),), root=root
    )
    assert lifted.loop_start == 2  # the loop began at "y", now the third step


def test_a_chain_of_reductions_is_lifted_one_after_the_other():
    root = build_structure(
        document=structure_to_document(structure=LOOP, source_id="n"), net_id="original"
    )
    chain = (link(x=("x", "y")), link(x=("x", "t")))
    lifted = lift_trace(trace=trace_of("x"), chain=chain, root=root)
    assert [s.transition.id for s in lifted.steps] == ["x", "t", "y"]


def test_a_step_the_original_net_does_not_have_is_refused():
    root = build_structure(
        document=structure_to_document(structure=LOOP, source_id="n"), net_id="original"
    )
    with pytest.raises(InvalidRequestError, match="ghost"):
        lift_trace(trace=trace_of("ghost"), chain=(link(),), root=root)


@pytest.fixture
def services(store, settings):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    runs = SqliteOperations(path=settings.database_path)
    operations = OperationService(
        nets=store,
        net_service=nets,
        runs=runs,
        engines=InProcessNative(),
        lease_seconds=60,
        wait_seconds=0,
    )
    # The counterexample found on the reduced net: x then y (x now stands for x then t).
    checks = CheckService(
        nets=store, jobs=store, engines=ScriptedEngines(trace_steps=("x", "y")), lease_seconds=LEASE
    )
    return nets, operations, checks, TraceService(checks=checks, nets=store, lineage=runs)


def test_a_counterexample_found_on_a_reduced_net_replays_on_the_original(services, store):
    nets, operations, checks, traces = services
    pnml = render_pnml(document=structure_to_document(structure=LOOP, source_id="n"))
    parent = nets.register(payload=pnml, format=NetFormat.PNML).stored.summary.net_id
    submission = operations.submit(
        net_id=parent,
        operation="fuse-series-places",
        request=OperationRequest(parameters=ReductionParameters(max_applications=1)),
    )
    operations.drain()
    child = operations.get(run_id=submission.run.run_id).outcome.result["new_net_id"]

    job = checks.submit(
        net_id=child,
        request=CheckRequest(
            formulas=(
                formula_from_text(
                    text='"q" >= 1', formula_id="f1", logic="state", gloss="", origin="user"
                ),
            ),
            engine="scripted",
        ),
    ).job
    checks.drain()

    on_reduced = traces.get(job_id=job.job_id, result_index=0, view="reduced")
    assert (on_reduced.net_id, [s.transition.id for s in on_reduced.steps]) == (child, ["x", "y"])
    on_original = traces.get(job_id=job.job_id, result_index=0, view="original")
    assert (on_original.net_id, [s.transition.id for s in on_original.steps]) == (
        parent,
        ["x", "t", "y"],
    )

    from app.application.inspection import InspectionService
    from app.domain.contract import PageRequest
    from app.domain.replay import ReplayRequest

    replayed = InspectionService(nets=store).replay(
        net_id=parent,
        request=ReplayRequest(
            steps=tuple(s.transition.id for s in on_original.steps), page=PageRequest(limit=1)
        ),
    )
    assert replayed.valid is True
    assert replayed.replayed == 3


def test_a_trace_on_an_uploaded_net_is_given_as_it_is(services):
    nets, _, checks, traces = services
    pnml = render_pnml(document=structure_to_document(structure=LOOP, source_id="n"))
    net_id = nets.register(payload=pnml, format=NetFormat.PNML).stored.summary.net_id
    job = checks.submit(
        net_id=net_id,
        request=CheckRequest(
            formulas=(
                formula_from_text(
                    text='"q" >= 1', formula_id="f1", logic="state", gloss="", origin="user"
                ),
            ),
            engine="scripted",
        ),
    ).job
    checks.drain()
    assert traces.get(job_id=job.job_id, result_index=0, view="original").net_id == net_id
