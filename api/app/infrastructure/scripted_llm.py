"""A scripted LLM: answers with prepared steps. It is the double of the LLM port (ADR 0009).

Tests use it for every agent test, and the ``scripted`` provider lets the platform and its UI run
without any key or network. It records what it was asked, so a test can check what the model saw.
"""

from __future__ import annotations

from app.domain.llm import LlmMessage, LlmStep, ToolSpec
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
