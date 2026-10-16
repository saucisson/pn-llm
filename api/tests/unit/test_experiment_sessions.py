import json

import pytest

from app.application.agent import AgentConfig, AgentService
from app.application.checks import CheckService
from app.application.experiment import ExperimentRunner
from app.application.experiment_sessions import ConditionAgent, ModelConditionRunner
from app.application.formulas import FormulaService
from app.application.inspection import InspectionService
from app.application.nets import NetService
from app.application.tools import ToolFacade
from app.domain.conditions import prompt_hash, tools_allowed
from app.domain.conversation import SYSTEM_PROMPT
from app.domain.errors import InvalidRequestError
from app.domain.experiment import ExperimentBudget, RunSpec
from app.domain.llm import LlmStep, LlmToolCall
from app.domain.net_validation import DocumentLimits
from app.domain.nets import NetFormat
from app.infrastructure.scripted_llm import ScriptedLlm
from tests.support import LEASE, MUTEX_PNML, ScriptedEngines, make_analysis_tools

KINDS = {"net_summary", "list_places", "check_formulas", "analyze", "analysis_summary", "ask_user"}


def call(tool, **arguments):
    return LlmToolCall(call_id=f"c-{tool}", tool=tool, arguments=json.dumps(arguments))


def check_call(*texts):
    formulas = [{"id": f"x{i}", "text": t} for i, t in enumerate(texts)]
    return call("check_formulas", formulas=formulas, timeout_s=5)


def world(*, store, steps, only=None, condition="L2"):
    engines = ScriptedEngines(verdict="TRUE", trace_steps=())
    checks = CheckService(nets=store, jobs=store, engines=engines, lease_seconds=LEASE)
    analyses = make_analysis_tools(store=store, path=store._path)
    tools = ToolFacade(
        inspection=InspectionService(nets=store),
        formulas=FormulaService(nets=store),
        checks=checks,
        analyses=analyses,
        max_result_chars=20_000,
        poll_seconds=0.001,
        only=only,
    )
    llm = ScriptedLlm(steps=steps)
    agent = AgentService(
        sessions=store,
        descriptions=store,
        nets=store,
        llm=llm,
        tools=tools,
        config=AgentConfig(
            max_steps=8, max_tool_calls=20, max_tokens=10**6, max_seconds=60, lease_seconds=LEASE
        ),
    )
    nets = NetService(nets=store, max_upload_bytes=10**6, limits=DocumentLimits())
    judge = ExperimentRunner(
        nets=nets, checks=checks, inspection=InspectionService(nets=store), analyses=analyses
    )
    runner = ModelConditionRunner(
        runner=judge,
        agents=(
            ConditionAgent(
                condition=condition,
                agent=agent,
                prompt_hash=prompt_hash(system=SYSTEM_PROMPT, tools=agent.tool_specs()),
            ),
        ),
        nets=nets,
        descriptions=store,
        model_id="scripted-model",
    )
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    return runner, llm, net_id


def spec(condition="L2"):
    return RunSpec(
        condition=condition,
        family="Mutex",
        repetition=0,
        seed="s",
        budget=ExperimentBudget(max_properties=5, check_timeout_s=5, mutants_per_operator=1),
    )


def test_what_the_model_proposed_is_measured_with_its_identity_and_the_session_is_kept(store):
    steps = (
        LlmStep(tool_calls=(check_call("crit1 >= 1", "AG (crit1 <= 1)"),)),
        LlmStep(tool_calls=(check_call("crit1 >= 1", "lock >= 1"),)),
        LlmStep(text="done"),
    )
    runner, _, net_id = world(store=store, steps=steps)
    record = runner.run(spec=spec(), net_id=net_id)
    assert record.spec.model_id == "scripted-model"
    assert record.spec.prompt_hash
    assert len(record.spec.prompt_hash) == 16
    assert record.session_id
    # "crit1 >= 1" was proposed twice and counts once; ids are renumbered per condition.
    assert record.proposed == 3
    assert [p.formula.id for p in record.properties] == ["L2-1", "L2-2", "L2-3"]
    assert {p.formula.origin for p in record.properties} == {"llm"}
    assert record.questions == 0


def test_a_question_is_answered_with_the_fixed_no_answer_and_counted(store):
    steps = (
        LlmStep(tool_calls=(call("ask_user", question="Which lock?"),)),
        LlmStep(tool_calls=(check_call("crit1 >= 1"),)),
        LlmStep(text="done"),
    )
    runner, llm, net_id = world(store=store, steps=steps)
    record = runner.run(spec=spec(), net_id=net_id)
    assert record.questions == 1
    seen = json.dumps([m.model_dump() for m in llm.requests[-1].messages])
    assert "No answer is available" in seen
    assert len(record.properties) == 1


def test_a_model_that_proposes_nothing_leaves_an_empty_record_not_a_crash(store):
    runner, _, net_id = world(store=store, steps=(LlmStep(text="nothing to say"),))
    record = runner.run(spec=spec(), net_id=net_id)
    assert (record.proposed, record.properties, record.mutants) == (0, (), ())
    assert record.non_triviality.share is None


def test_a_condition_without_an_agent_or_l3_without_a_description_is_refused(store):
    runner, _, net_id = world(store=store, steps=())
    with pytest.raises(InvalidRequestError, match="No agent"):
        runner.run(spec=spec("L1"), net_id=net_id)
    l3, _, net3 = world(store=store, steps=(), condition="L3")
    with pytest.raises(InvalidRequestError, match="No description"):
        l3.run(spec=spec("L3"), net_id=net3)


def test_the_obfuscated_net_hides_the_names_and_the_properties_come_back_in_original_names(store):
    steps = (
        LlmStep(tool_calls=(call("list_places"),)),
        LlmStep(tool_calls=(check_call("p1 >= 1"),)),
        LlmStep(text="done"),
    )
    runner, llm, net_id = world(store=store, steps=steps, condition="N")
    record = runner.run(spec=spec("N"), net_id=net_id)
    assert "crit1" not in json.dumps([m.model_dump() for m in llm.requests[1].messages])
    (kept,) = record.properties
    assert "crit1" in json.dumps(kept.formula.model_dump())  # p1 is crit1 (sorted ids)
    assert record.net_id == net_id


def test_l1_is_not_given_the_analysis_tools_or_their_facts(store):
    offered = tuple(KINDS)
    assert "analyze" not in tools_allowed(condition="L1", offered=offered)
    assert tools_allowed(condition="L2", offered=offered) == frozenset(offered)
    steps = (LlmStep(tool_calls=(check_call("lock >= 1"),)), LlmStep(text="done"))
    only = tools_allowed(condition="L1", offered=("net_summary", "check_formulas", "analyze"))
    runner, llm, net_id = world(store=store, steps=steps, only=only, condition="L1")
    record = runner.run(spec=spec("L1"), net_id=net_id)
    assert {t.name for t in llm.requests[0].tools} == {"net_summary", "check_formulas"}
    answer = next(m.text for m in llm.requests[1].messages if m.role == "tool")
    assert "trivial" not in answer
    assert "next_moves" not in answer
    assert len(record.properties) == 1
