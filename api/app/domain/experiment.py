"""What one experimental run is and what it leaves behind (docs/evaluation.md).

A run is one condition on one net of one family, for one repetition. Whatever produced the
properties (the rule-based baseline or a language model), the run records the same things: what was
asked, what engines said, what the structure says about each property, how the mutants fared, and
everything needed to reproduce it (seeds, budgets, tool versions, model, prompt, code version).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .formula import Formula
from .models import DomainModel, Verdict
from .mutation import OPERATORS, MutationOperator
from .mutation_score import MutantJudgement, MutationScore, PropertyOutcome
from .non_triviality import FamilyNonTriviality, PropertyFindings

Condition = Literal["B0", "L1", "L2", "L3", "N"]


class ExperimentBudget(DomainModel):
    """The limits every condition gets, the baseline included (budget parity)."""

    max_properties: int = Field(default=20, ge=1, le=1000)
    check_timeout_s: int = Field(default=60, ge=1, le=3600)
    mutants_per_operator: int = Field(default=3, ge=0, le=100)
    operators: tuple[MutationOperator, ...] = OPERATORS


class RunSpec(DomainModel):
    """The inputs of a run that make it reproducible."""

    condition: Condition
    family: str
    repetition: int = Field(ge=0)
    seed: str
    budget: ExperimentBudget
    git_commit: str | None = None
    # Absent for the rule-based baseline.
    model_id: str | None = None
    prompt_hash: str | None = None


class ToolVersion(DomainModel):
    """An engine and the version that answered."""

    name: str
    version: str


class MeasuredProperty(DomainModel):
    """A property of the set and the verdict an engine gave it on the original net."""

    formula: Formula
    verdict: Verdict
    engine: str
    engine_version: str


class MutantRecord(DomainModel):
    """One mutant, how each property fared on it, and the judgement."""

    description: str
    operator: MutationOperator
    net_id: str | None
    outcomes: tuple[PropertyOutcome, ...]
    judgement: MutantJudgement


class RunRecord(DomainModel):
    """Everything a run measured, ready to be stored and analysed by family."""

    spec: RunSpec
    net_id: str
    tools: tuple[ToolVersion, ...]
    properties: tuple[MeasuredProperty, ...]
    findings: tuple[PropertyFindings, ...]
    non_triviality: FamilyNonTriviality
    mutants: tuple[MutantRecord, ...]
    mutation: MutationScore
