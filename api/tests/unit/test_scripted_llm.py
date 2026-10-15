import pytest

from app.domain.llm import LlmMessage, LlmStep, LlmToolCall, ToolSpec
from app.infrastructure.scripted_llm import ScriptedLlm, ScriptExhaustedError


def ask(llm):
    return llm.next_step(
        system="s",
        messages=(LlmMessage(role="user", text="hi"),),
        tools=(ToolSpec(name="t", description="d", input_schema="{}"),),
    )


def test_it_answers_with_the_prepared_steps_in_order_and_remembers_the_requests():
    call = LlmToolCall(call_id="c1", tool="net_summary", arguments="{}")
    llm = ScriptedLlm(steps=(LlmStep(tool_calls=(call,)), LlmStep(text="done")))
    assert ask(llm).tool_calls == (call,)
    assert ask(llm).text == "done"
    assert [r.system for r in llm.requests] == ["s", "s"]
    assert llm.requests[0].messages[0].text == "hi"
    assert llm.requests[0].tools[0].name == "t"


def test_it_fails_loudly_when_the_script_runs_out():
    llm = ScriptedLlm(steps=())
    with pytest.raises(ScriptExhaustedError):
        ask(llm)
