"""The arguments of the tools offered to the LLM, one model per tool (ADR 0009, ADR 0013).

Their JSON Schemas are what the model is shown. Names mirror the operations of the API; none of
them returns the net itself.
"""

from __future__ import annotations

from pydantic import Field, JsonValue

from .formula import Logic
from .models import DomainModel

TOOL_PAGE_LIMIT = 30
TOOL_PAGE_MAX = 100


class NoArguments(DomainModel):
    """A tool that takes nothing."""


class PageArguments(DomainModel):
    """Pagination of a list: the cursor comes from the ``truncated`` field of the previous page."""

    limit: int = Field(default=TOOL_PAGE_LIMIT, ge=1, le=TOOL_PAGE_MAX)
    cursor: str | None = None


class ListPlacesArguments(PageArguments):
    """Places sorted by id, optionally filtered."""

    name: str | None = Field(default=None, description="Glob on the name: * and ?")
    marked: bool | None = Field(default=None, description="Hold tokens initially (P/T nets)")


class ListTransitionsArguments(PageArguments):
    """Transitions sorted by id, optionally filtered."""

    name: str | None = Field(default=None, description="Glob on the name: * and ?")


class ListArcsArguments(PageArguments):
    """Arcs sorted by id, optionally from a source or to a target element."""

    source: str | None = Field(default=None, description="Id of the source element")
    target: str | None = Field(default=None, description="Id of the target element")


class ElementArguments(DomainModel):
    """One place or transition, by id."""

    element_id: str


class SearchArguments(PageArguments):
    """Find places and transitions by name or id."""

    query: str = Field(min_length=1, description="Text or glob, case-insensitive")


class NeighbourhoodArguments(DomainModel):
    """Elements near some elements."""

    ids: tuple[str, ...] = Field(min_length=1)
    depth: int = Field(default=1, ge=0, le=5)
    max_elements: int = Field(default=50, ge=1, le=500)


class NameGroupsArguments(PageArguments):
    """Families of indexed names."""

    min_count: int = Field(default=2, ge=2)


class FormulaText(DomainModel):
    """A property written in the text syntax of docs/formula-syntax.md."""

    id: str = Field(min_length=1, description="Your name for the property, unique in the call")
    text: str = Field(min_length=1)
    logic: Logic | None = Field(default=None, description="ltl, ctl or state; inferred if absent")
    gloss: str = Field(default="", description="The property in plain words, for the user")


class ValidateFormulaArguments(DomainModel):
    """Check a formula against the net without running an engine."""

    formula: FormulaText


class CheckFormulasArguments(DomainModel):
    """Verify some properties with an engine."""

    formulas: tuple[FormulaText, ...] = Field(min_length=1, max_length=10)
    engine: str = "auto"
    timeout_s: int = Field(default=60, ge=1, le=600)
    portfolio: int = Field(
        default=1, ge=1, le=4, description="With engine auto: ask this many engines at once"
    )
    cross_check: bool = Field(
        default=False, description="Wait for every engine of the portfolio and compare them"
    )


class TraceArguments(DomainModel):
    """The counterexample of one result of a check."""

    job_id: str
    result_index: int = Field(ge=0)


class ReplayArguments(DomainModel):
    """Fire transitions in order on a P/T net."""

    steps: tuple[str, ...] = Field(description="Transition ids, in order")
    state_formula: str | None = Field(
        default=None, description="A condition without temporal operator, tested at the end"
    )


class AskUserArguments(DomainModel):
    """Ask the user a question and wait for the answer."""

    question: str = Field(min_length=1)


class ProposeDescriptionArguments(DomainModel):
    """Offer a clearer description of the system to the user, who may accept it."""

    text: str = Field(min_length=1, max_length=8_000)


class AnalyzeArguments(DomainModel):
    """Run one structural analysis of the net."""

    operation: str = Field(description="Name of the analysis, from the list in the description")
    parameters: dict[str, JsonValue] = Field(
        default_factory=dict, description="Options of that analysis; most need none"
    )
