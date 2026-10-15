import json
from types import SimpleNamespace

import anthropic
import pytest

from app.domain.errors import LlmUnavailableError
from app.domain.llm import LlmMessage, LlmToolCall, ToolSpec
from app.infrastructure.anthropic_llm import (
    AnthropicLlm,
    to_anthropic_messages,
    to_anthropic_tools,
)

SCHEMA = json.dumps({"type": "object", "properties": {"limit": {"type": "integer"}}})
TOOLS = (
    ToolSpec(name="net_summary", description="counts", input_schema=SCHEMA),
    ToolSpec(name="list_places", description="places", input_schema=SCHEMA),
)


def call(call_id, tool="net_summary", arguments="{}"):
    return LlmToolCall(call_id=call_id, tool=tool, arguments=arguments)


def test_the_conversation_becomes_alternating_turns_with_results_right_after_their_calls():
    messages = (
        LlmMessage(role="user", text="goal"),
        LlmMessage(
            role="assistant",
            text="looking",
            tool_calls=(call("a"), call("b", "list_places", '{"limit": 3}')),
        ),
        LlmMessage(role="tool", text="A", tool_call_id="a"),
        LlmMessage(role="tool", text="B", tool_call_id="b", tool_ok=False),
        LlmMessage(role="user", text="and then?"),
    )
    converted = to_anthropic_messages(messages=messages)
    assert [m["role"] for m in converted] == ["user", "assistant", "user"]
    assistant = converted[1]["content"]
    assert assistant[0] == {"type": "text", "text": "looking"}
    assert assistant[1] == {"type": "tool_use", "id": "a", "name": "net_summary", "input": {}}
    assert assistant[2]["input"] == {"limit": 3}
    last = converted[2]["content"]
    assert [block["type"] for block in last] == ["tool_result", "tool_result", "text"]
    assert last[0]["tool_use_id"] == "a"
    assert last[0]["is_error"] is False
    assert last[1]["tool_use_id"] == "b"
    assert last[1]["is_error"] is True
    assert last[2]["text"] == "and then?"


def test_consecutive_user_messages_share_a_turn_and_an_empty_assistant_step_is_skipped():
    converted = to_anthropic_messages(
        messages=(
            LlmMessage(role="user", text="one"),
            LlmMessage(role="user", text="two"),
            LlmMessage(role="assistant", text=""),
        )
    )
    assert [m["role"] for m in converted] == ["user"]
    assert [b["text"] for b in converted[0]["content"]] == ["one", "two"]


def test_invalid_json_arguments_become_an_empty_input_not_a_crash():
    converted = to_anthropic_messages(
        messages=(LlmMessage(role="assistant", tool_calls=(call("a", arguments="{oops"),)),)
    )
    assert converted[0]["content"][0]["input"] == {}


def test_only_the_last_tool_carries_the_cache_breakpoint():
    tools = to_anthropic_tools(tools=TOOLS)
    assert "cache_control" not in tools[0]
    assert tools[1]["cache_control"] == {"type": "ephemeral"}
    assert tools[0]["input_schema"]["type"] == "object"
    assert to_anthropic_tools(tools=()) == []


class FakeMessages:
    """The Messages endpoint of the SDK: records the request, answers or fails as told."""

    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def llm_with(fake):
    gateway = AnthropicLlm(api_key="sk-test", model="claude-opus-4-8", max_tokens=1000)
    gateway._client = SimpleNamespace(messages=fake)
    return gateway


def answer(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
    )


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(call_id, name, arguments):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def test_the_request_carries_the_model_the_system_prompt_the_tools_and_no_thinking():
    fake = FakeMessages(response=answer(text("hi")))
    llm_with(fake).next_step(
        system="rules", messages=(LlmMessage(role="user", text="go"),), tools=TOOLS
    )
    (request,) = fake.requests
    assert request["model"] == "claude-opus-4-8"
    assert request["max_tokens"] == 1000
    assert request["system"] == [
        {"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}}
    ]
    assert request["thinking"] == {"type": "disabled"}
    assert [t["name"] for t in request["tools"]] == ["net_summary", "list_places"]
    assert request["messages"][0]["role"] == "user"


def test_the_answer_becomes_text_tool_calls_and_token_counts():
    fake = FakeMessages(
        response=answer(text("first"), tool_use("t1", "list_places", {"limit": 5}), text("second"))
    )
    step = llm_with(fake).next_step(system="s", messages=(), tools=TOOLS)
    assert step.text == "first\nsecond"
    assert [(c.call_id, c.tool, json.loads(c.arguments)) for c in step.tool_calls] == [
        ("t1", "list_places", {"limit": 5})
    ]
    assert (step.input_tokens, step.output_tokens) == (120, 30)


def test_a_refusal_is_reported_as_the_model_being_unusable_for_this_request():
    fake = FakeMessages(response=answer(stop_reason="refusal"))
    with pytest.raises(LlmUnavailableError, match="declined"):
        llm_with(fake).next_step(system="s", messages=(), tools=())


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=object()),
        anthropic.AuthenticationError(
            "bad key",
            response=SimpleNamespace(status_code=401, headers={}, request=None),
            body=None,
        ),
    ],
    ids=["connection", "authentication"],
)
def test_a_key_or_network_problem_is_unavailability_without_leaking_details(error):
    fake = FakeMessages(error=error)
    with pytest.raises(LlmUnavailableError) as caught:
        llm_with(fake).next_step(system="s", messages=(), tools=())
    assert "sk-test" not in str(caught.value)


def test_other_errors_propagate_so_the_run_records_them():
    fake = FakeMessages(error=ValueError("bug"))
    with pytest.raises(ValueError, match="bug"):
        llm_with(fake).next_step(system="s", messages=(), tools=())
