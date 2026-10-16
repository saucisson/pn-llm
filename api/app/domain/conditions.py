"""What each experimental condition gives the language model (docs/evaluation.md).

L1 sees the net through inspection alone: sizes, names, neighbourhoods. L2 adds static-analysis
facts (the analysis tools and the structural verdict on each checked property). L3 adds the
description of the system. N is L2 on a net whose names were replaced. The system prompt and the
budgets are the same for all of them.
"""

from __future__ import annotations

import hashlib

from .experiment import Condition
from .llm import ToolSpec

# What L1 is not given: static analysis, and the choice of engine.
ANALYSIS_TOOLS = frozenset({"analysis_summary", "analyze", "select_tools"})
GOAL = (
    "Propose properties worth verifying on this system, check them with the engines, and report "
    "what you found. Cover different kinds of properties."
)
NO_ANSWER = "No answer is available: continue with what you have."


def tools_allowed(*, condition: Condition, offered: tuple[str, ...]) -> frozenset[str]:
    """Return the names of the tools a condition may use among the ones the platform offers."""
    if condition == "L1":
        return frozenset(offered) - ANALYSIS_TOOLS
    return frozenset(offered)


def gives_description(*, condition: Condition) -> bool:
    """Tell whether the condition shows the description of the system to the model."""
    return condition == "L3"


def prompt_hash(*, system: str, tools: tuple[ToolSpec, ...]) -> str:
    """Return a short hash of everything the model is told besides the net: prompt and tools."""
    text = system + "\n".join(f"{t.name}|{t.description}|{t.input_schema}" for t in tools)
    return hashlib.sha256(text.encode()).hexdigest()[:16]
