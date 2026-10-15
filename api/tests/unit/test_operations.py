import threading

import pytest

from app.application.nets import NetService
from app.application.operations import OperationService
from app.domain.analyses.p_invariants import PInvariantsParameters
from app.domain.contract import ElementRef
from app.domain.engine_contract import EngineOperationReport
from app.domain.errors import InvalidRequestError, NotFoundError
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from app.domain.operation_check import interpret_operation_report
from app.domain.operations import NoParameters, OperationRequest, RunState
from app.infrastructure.sqlite_operations import SqliteOperations
from tests.support import InProcessNative, query

SYMMETRIC = "http://www.pnml.org/version-2009/grammar/symmetricnet"
COLORED = f"""<pnml><net id="c" type="{SYMMETRIC}"><page id="p">
<place id="p1"><name><text>p1</text></name><type><text>D</text>
<structure><usersort declaration="D"/></structure></type></place>
<transition id="t1"/>
<arc id="a1" source="p1" target="t1"/>
</page></net></pnml>""".encode()


@pytest.fixture
def engines():
    return InProcessNative()


@pytest.fixture
def operations(store, settings, engines):
    return OperationService(
        nets=store,
        runs=SqliteOperations(path=settings.database_path),
        engines=engines,
        lease_seconds=60,
        wait_seconds=0,
    )


@pytest.fixture
def net_id(store, mutex_pnml):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    return nets.register(payload=mutex_pnml, format=NetFormat.PNML).stored.summary.net_id


def invariants(*, engine="auto", **parameters):
    return OperationRequest(engine=engine, parameters=PInvariantsParameters(**parameters))


def test_the_catalog_describes_every_operation_with_the_engines_that_perform_it(operations):
    catalog = {entry.name: entry for entry in operations.catalog()}
    assert set(catalog) == {"net-class", "p-invariants"}
    entry = catalog["p-invariants"]
    assert entry.route == "/v1/nets/{net_id}/analyses/p-invariants"
    assert entry.engines == ("native",)
    assert "max_rows" in entry.parameters_schema["properties"]
    assert "invariants" in entry.result_schema["properties"]


def test_a_catalog_lists_no_engine_whose_image_is_missing(store, settings):
    service = OperationService(
        nets=store,
        runs=SqliteOperations(path=settings.database_path),
        engines=InProcessNative(available=False),
        lease_seconds=60,
        wait_seconds=0,
    )
    assert all(entry.engines == () for entry in service.catalog())


def test_a_submitted_run_is_queued_then_done_with_the_result(operations, net_id):
    submission = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    assert (submission.created, submission.run.state) == (True, RunState.QUEUED)
    assert operations.drain() == 1
    run = operations.get(run_id=submission.run.run_id)
    assert run.state is RunState.DONE
    assert run.outcome.tool.name == "native"
    assert run.outcome.result["total"] == 2


def test_the_same_question_is_answered_from_the_finished_run(operations, net_id, engines):
    first = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    operations.drain()
    again = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    assert (again.created, again.run.run_id, again.run.state) == (
        False,
        first.run.run_id,
        RunState.DONE,
    )
    assert engines.calls == ["p-invariants"]  # computed once


def test_other_parameters_or_another_operation_are_other_runs(operations, net_id):
    base = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    other = operations.submit(
        net_id=net_id, operation="p-invariants", request=invariants(max_invariants=1)
    )
    unrelated = operations.submit(
        net_id=net_id,
        operation="net-class",
        request=OperationRequest(parameters=NoParameters()),
    )
    assert len({base.run.run_id, other.run.run_id, unrelated.run.run_id}) == 3


def test_limits_do_not_make_a_different_question(operations, net_id):
    first = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    again = operations.submit(
        net_id=net_id,
        operation="p-invariants",
        request=OperationRequest(
            parameters=PInvariantsParameters(), limits={"timeout_s": 5, "memory_mb": 128}
        ),
    )
    assert again.run.run_id == first.run.run_id


def test_unknown_net_operation_and_engine_are_refused(operations, net_id):
    with pytest.raises(NotFoundError):
        operations.submit(net_id="nope", operation="p-invariants", request=invariants())
    with pytest.raises(NotFoundError):
        operations.submit(net_id=net_id, operation="nope", request=invariants())
    with pytest.raises(InvalidRequestError):
        operations.submit(
            net_id=net_id, operation="p-invariants", request=invariants(engine="tapaal")
        )


def test_a_colored_net_is_refused_where_the_operation_does_not_handle_it(operations, store):
    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    colored = nets.register(payload=COLORED, format=NetFormat.PNML).stored.summary.net_id
    with pytest.raises(InvalidRequestError, match="colored"):
        operations.submit(net_id=colored, operation="p-invariants", request=invariants())


def test_a_slow_run_can_be_waited_for_and_cancelled(operations, net_id, engines):
    gate = threading.Event()
    engines.gate = gate
    submission = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    worker = threading.Thread(target=operations.run_next)
    worker.start()
    waiting = operations.wait(run_id=submission.run.run_id, seconds=0.2)
    assert waiting.state is RunState.RUNNING
    operations.cancel(run_id=submission.run.run_id)
    gate.set()
    worker.join()
    run = operations.get(run_id=submission.run.run_id)
    assert run.state is RunState.CANCELLED  # the answer of a cancelled run is not wanted
    assert run.outcome is None
    assert engines.stopped == [submission.run.run_id]
    again = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    assert again.created is True  # a cancelled run does not hold the key


def test_a_run_whose_owner_died_is_interrupted_and_can_be_asked_again(operations, net_id, settings):
    submission = operations.submit(
        net_id=net_id, operation="net-class", request=OperationRequest(parameters=NoParameters())
    )
    runs = SqliteOperations(path=settings.database_path)
    assert runs.claim_next_run(lease_seconds=-1).run_id == submission.run.run_id
    assert operations.recover_interrupted() == 1
    assert operations.get(run_id=submission.run.run_id).state is RunState.INTERRUPTED
    again = operations.submit(
        net_id=net_id, operation="net-class", request=OperationRequest(parameters=NoParameters())
    )
    assert again.created is True


def test_an_engine_that_cites_an_element_not_in_the_net_fails_the_run(store, settings, net_id):
    def lie(report):
        result = dict(report.result)
        result["uncovered_places"] = [{"id": "ghost", "name": "ghost", "kind": "place"}]
        return report.model_copy(update={"result": result})

    service = OperationService(
        nets=store,
        runs=SqliteOperations(path=settings.database_path),
        engines=InProcessNative(tamper=lie),
        lease_seconds=60,
        wait_seconds=0,
    )
    submission = service.submit(net_id=net_id, operation="p-invariants", request=invariants())
    service.drain()
    run = service.get(run_id=submission.run.run_id)
    assert run.state is RunState.FAILED
    assert run.outcome.error.code == "result_cites_unknown_element"
    assert run.outcome.result is None
    # a failed run does not hold the key: asking again is a new run
    assert service.submit(net_id=net_id, operation="p-invariants", request=invariants()).created


def test_a_crash_of_the_runner_ends_the_run_failed_with_the_reason(store, settings, net_id):
    def crash(report):
        raise RuntimeError("adapter bug")

    service = OperationService(
        nets=store,
        runs=SqliteOperations(path=settings.database_path),
        engines=InProcessNative(tamper=crash),
        lease_seconds=60,
        wait_seconds=0,
    )
    submission = service.submit(
        net_id=net_id, operation="net-class", request=OperationRequest(parameters=NoParameters())
    )
    service.drain()
    run = service.get(run_id=submission.run.run_id)
    assert (run.state, run.outcome.error.code) == (RunState.FAILED, "runner_exception_RuntimeError")


def test_unknown_runs_are_not_found(operations):
    with pytest.raises(NotFoundError):
        operations.get(run_id="nope")
    with pytest.raises(NotFoundError):
        operations.cancel(run_id="nope")


def test_old_finished_runs_are_purged_and_queued_ones_are_not(operations, net_id, settings):
    done = operations.submit(
        net_id=net_id, operation="net-class", request=OperationRequest(parameters=NoParameters())
    )
    operations.drain()
    waiting = operations.submit(net_id=net_id, operation="p-invariants", request=invariants())
    import sqlite3

    conn = sqlite3.connect(settings.database_path)
    conn.execute("UPDATE operation_runs SET updated_at=0")
    conn.commit()
    conn.close()
    assert operations.purge_old_runs(retention_s=86_400) == 1
    with pytest.raises(NotFoundError):
        operations.get(run_id=done.run.run_id)
    assert operations.get(run_id=waiting.run.run_id).state is RunState.QUEUED


def test_deleting_a_net_removes_its_runs(operations, net_id, settings):
    from app.infrastructure.sqlite_retention import SqliteRetention

    operations.submit(
        net_id=net_id, operation="net-class", request=OperationRequest(parameters=NoParameters())
    )
    assert SqliteRetention(path=settings.database_path).delete_net(net_id=net_id) is True
    assert query(path=settings.database_path, sql="SELECT count(*) FROM operation_runs") == [(0,)]


# ---- what an engine says is checked ---------------------------------------------------------


def report(*, result, **fields):
    return EngineOperationReport(status="ok", result=result, **fields)


def test_a_result_of_the_wrong_shape_is_refused(operations, net_id, store):
    from app.domain.analyses import find_operation
    from app.domain.net_structure import build_structure

    structure = build_structure(document=store.load_net(net_id=net_id).document, net_id=net_id)
    outcome = interpret_operation_report(
        report=report(result={"unexpected": 1}),
        definition=find_operation(name="net-class"),
        engine="native",
        engine_version="1.0",
        structure=structure,
    )
    assert (outcome.status, outcome.error.code) == ("failed", "invalid_result")


def test_a_different_name_for_a_real_id_is_refused_and_a_different_version_is_noted(store, net_id):
    from app.domain.analyses import find_operation
    from app.domain.net_structure import build_structure

    structure = build_structure(document=store.load_net(net_id=net_id).document, net_id=net_id)
    definition = find_operation(name="p-invariants")
    renamed = {
        "invariants": [],
        "total": 0,
        "complete": True,
        "uncovered_places": [ElementRef(id="lock", name="mutex lock", kind="place").model_dump()],
    }
    refused = interpret_operation_report(
        report=report(result=renamed),
        definition=definition,
        engine="native",
        engine_version="1.0",
        structure=structure,
    )
    assert refused.error.code == "result_cites_unknown_element"
    honest = {**renamed, "uncovered_places": []}
    accepted = interpret_operation_report(
        report=report(result=honest, tool_name="native", tool_version="9.9"),
        definition=definition,
        engine="native",
        engine_version="1.0",
        structure=structure,
    )
    assert accepted.status == "ok"
    assert accepted.tool.version == "9.9"
    assert accepted.warnings == ("tool_version_differs_from_registry:9.9",)


def test_a_failed_report_is_a_failed_outcome_with_its_code(store, net_id):
    from app.domain.analyses import find_operation
    from app.domain.net_structure import build_structure

    structure = build_structure(document=store.load_net(net_id=net_id).document, net_id=net_id)
    outcome = interpret_operation_report(
        report=EngineOperationReport(status="failed", error_code="timeout", elapsed_s=3),
        definition=find_operation(name="net-class"),
        engine="native",
        engine_version="1.0",
        structure=structure,
    )
    assert (outcome.status, outcome.error.code, outcome.elapsed_s) == ("failed", "timeout", 3)
