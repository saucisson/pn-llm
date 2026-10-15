import json

import pytest

from tests.support import MUTEX_DOCUMENT, InProcessNative, make_analysis_tools
from tests.unit.test_operations import COLORED
from tests.unit.test_tools import build, call, context_for, payload, save


@pytest.fixture
def mutex_net(store):
    return save(store=store, document=MUTEX_DOCUMENT)


def test_analysis_tools_are_offered_with_the_analysis_names(store):
    facade, _ = build(store=store)
    by_name = {spec.name: spec for spec in facade.specs()}
    assert {"analysis_summary", "analyze"} <= set(by_name)
    assert "p-invariants" in by_name["analyze"].description
    assert "minimal-siphons" in by_name["analyze"].description


def test_the_summary_tool_gives_a_digest_with_named_invariants(store, mutex_net):
    facade, _ = build(store=store)
    outcome = call(facade, context_for(net_id=mutex_net), "analysis_summary")
    assert outcome.ok
    data = payload(outcome)["data"]
    assert "marked graph" in data["net_class"]
    assert sorted(data["place_invariants"]["examples"]) == ["crit1 + idle1 = 1", "crit1 + lock = 1"]
    assert data["bounds"] == {"finite": 3, "unbounded": 0, "unknown": 0, "largest_finite_bound": 1}
    assert data["components"]["count"] == 1
    assert data["unavailable"] == []
    assert len(outcome.content) <= 4_000


def test_the_analyze_tool_runs_one_analysis_and_names_the_tool(store, mutex_net):
    facade, _ = build(store=store)
    outcome = call(
        facade,
        context_for(net_id=mutex_net),
        "analyze",
        {"operation": "t-invariants", "parameters": {"max_invariants": 5}},
    )
    data = payload(outcome)["data"]
    assert data["operation"] == "t-invariants"
    assert data["tool"] == {"name": "native", "version": "1.0"}
    assert data["result"]["total"] == 1


def test_mistakes_come_back_as_errors_the_model_can_read(store, mutex_net):
    facade, _ = build(store=store)
    unknown = call(facade, context_for(net_id=mutex_net), "analyze", {"operation": "nope"})
    assert (unknown.ok, "Unknown analysis" in unknown.content) == (False, True)
    bad = call(
        facade,
        context_for(net_id=mutex_net),
        "analyze",
        {"operation": "p-invariants", "parameters": {"max_rows": 0}},
    )
    assert (bad.ok, "Invalid parameters" in bad.content) == (False, True)
    never = call(
        facade,
        context_for(net_id=mutex_net),
        "analyze",
        {"operation": "p-invariants"},
        cancelled=True,
    )
    assert never.ok is False


def test_without_a_native_engine_the_summary_lists_what_it_could_not_do(store, mutex_net, settings):
    from app.application.checks import CheckService
    from app.application.formulas import FormulaService
    from app.application.inspection import InspectionService
    from app.application.tools import ToolFacade
    from tests.support import LEASE, ScriptedEngines

    facade = ToolFacade(
        inspection=InspectionService(nets=store),
        formulas=FormulaService(nets=store),
        checks=CheckService(nets=store, jobs=store, engines=ScriptedEngines(), lease_seconds=LEASE),
        analyses=make_analysis_tools(
            store=store, path=settings.database_path, engines=InProcessNative(available=False)
        ),
        max_result_chars=20_000,
        poll_seconds=0.001,
    )
    data = payload(call(facade, context_for(net_id=mutex_net), "analysis_summary"))["data"]
    assert [u["operation"] for u in data["unavailable"]][:2] == ["net-class", "p-invariants"]
    assert len(data["unavailable"]) == 7
    assert "place_invariants" not in data  # absent, not zero


def test_a_colored_net_gets_reasons_not_numbers(store):
    from app.application.nets import NetService
    from app.domain.net_validation import DocumentLimits
    from app.domain.nets import NetFormat

    nets = NetService(nets=store, max_upload_bytes=1_000_000, limits=DocumentLimits())
    colored = nets.register(payload=COLORED, format=NetFormat.PNML).stored.summary.net_id
    facade, _ = build(store=store)
    data = payload(call(facade, context_for(net_id=colored), "analysis_summary"))["data"]
    assert len(data["unavailable"]) == 7
    assert "colored" in data["unavailable"][0]["reason"]
    failure = call(facade, context_for(net_id=colored), "analyze", {"operation": "net-class"})
    assert (failure.ok, "colored" in failure.content) == (False, True)


def test_the_digest_never_contains_the_net(store, mutex_net):
    facade, _ = build(store=store)
    outcome = call(facade, context_for(net_id=mutex_net), "analysis_summary")
    assert "<pnml" not in outcome.content
    assert json.loads(outcome.content)["status"] == "ok"
