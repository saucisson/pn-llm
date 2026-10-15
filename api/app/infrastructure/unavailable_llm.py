"""The language model when none is configured: it says so instead of failing obscurely."""

from __future__ import annotations

from app.domain.errors import LlmUnavailableError
from app.domain.llm import LlmMessage, LlmStep, ToolSpec


class UnavailableLlm:
    """An LLM gateway that always refuses, with the setting that would fix it."""

    def next_step(
        self, *, system: str, messages: tuple[LlmMessage, ...], tools: tuple[ToolSpec, ...]
    ) -> LlmStep:
        """Refuse.

        Raises:
            LlmUnavailableError: always.
        """
        raise LlmUnavailableError(
            "No language model is configured: set PNVERIF_LLM_PROVIDER (scripted or anthropic)"
        )
