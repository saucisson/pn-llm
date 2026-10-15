"""A scripted LLM: answers with prepared steps. It is the double of the LLM port (ADR 0009).

Tests use it for every agent test, and the ``scripted`` provider lets the platform and its UI run
without any key or network. It records what it was asked, so a test can check what the model saw.
"""

from __future__ import annotations

import json

from app.domain.llm import LlmMessage, LlmStep, LlmToolCall, ToolSpec
from app.domain.models import DomainModel


class LlmRequest(DomainModel):
    """One request the scripted LLM received."""

    system: str
    messages: tuple[LlmMessage, ...]
    tools: tuple[ToolSpec, ...]


class ScriptExhaustedError(Exception):
    """The agent asked for more steps than the script holds."""


class ScriptedLlm:
    """Returns the prepared steps in order and remembers the requests."""

    def __init__(self, *, steps: tuple[LlmStep, ...]) -> None:
        """Prepare the script."""
        self._steps = list(steps)
        self.requests: list[LlmRequest] = []

    def next_step(
        self, *, system: str, messages: tuple[LlmMessage, ...], tools: tuple[ToolSpec, ...]
    ) -> LlmStep:
        """Return the next prepared step.

        Raises:
            ScriptExhaustedError: if every step was used.
        """
        self.requests.append(LlmRequest(system=system, messages=messages, tools=tools))
        if not self._steps:
            raise ScriptExhaustedError(f"The script has no step {len(self.requests)}")
        return self._steps.pop(0)


class DemoLlm:
    """A stateless offline demonstration of the agent: look at the net, test deadlock, conclude.

    It decides from the conversation alone, so any number of sessions can use it at once. It makes
    no claim of its own: the conclusion repeats what the tools returned.
    """

    def next_step(
        self, *, system: str, messages: tuple[LlmMessage, ...], tools: tuple[ToolSpec, ...]
    ) -> LlmStep:
        """Return the next step of the demonstration."""
        answers = [message for message in messages if message.role == "tool"]
        if not answers:
            call = LlmToolCall(call_id="demo-1", tool="net_summary", arguments="{}")
            return LlmStep(text="I start by looking at the size of the net.", tool_calls=(call,))
        if len(answers) == 1:
            arguments = json.dumps(
                {
                    "formulas": [
                        {
                            "id": "no_deadlock",
                            "text": "deadlock",
                            "logic": "state",
                            "gloss": "Some reachable marking blocks every transition.",
                        }
                    ],
                    "timeout_s": 30,
                }
            )
            call = LlmToolCall(call_id="demo-2", tool="check_formulas", arguments=arguments)
            return LlmStep(
                text="Let me ask an engine whether the net can block.", tool_calls=(call,)
            )
        return LlmStep(
            text=(
                "This is the offline demonstration: the engine's answer is in the verdict above. "
                "Configure a language model (PNVERIF_LLM_PROVIDER) for a real analysis."
            )
        )
