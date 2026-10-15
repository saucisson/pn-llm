"""The language model when none is configured: it says so instead of failing obscurely."""

from __future__ import annotations

from app.domain.errors import LlmUnavailableError
from app.domain.llm import LlmMessage, LlmStep, ToolSpec

NOT_CONFIGURED = "No language model is configured: set PNVERIF_LLM_PROVIDER (scripted or anthropic)"


class UnavailableLlm:
    """An LLM gateway that always refuses, with the setting that would fix it."""

    def __init__(self, *, reason: str = NOT_CONFIGURED) -> None:
        """Create the gateway with the reason it gives."""
        self._reason = reason

    def next_step(
        self, *, system: str, messages: tuple[LlmMessage, ...], tools: tuple[ToolSpec, ...]
    ) -> LlmStep:
        """Refuse.

        Raises:
            LlmUnavailableError: always.
        """
        raise LlmUnavailableError(self._reason)
