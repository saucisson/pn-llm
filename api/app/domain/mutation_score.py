"""Judge mutants against a property set and score the set (measures M5 and M6).

A property kills a mutant when its verdict on the mutant differs from its verdict on the original,
both being definitive (TRUE or FALSE). A timeout, an out-of-memory, an UNKNOWN or an error is not a
verdict, so it never kills and never clears: a mutant that no property killed and that some
property could not decide on either net is *undecided*. A mutant that every property decided on
both nets and none killed *survived*; the platform does not claim it is equivalent to the
original (CLAUDE.md, evaluation rules). Families are aggregated before conditions.
"""

from __future__ import annotations

from typing import Literal

from .models import DomainModel, Verdict

DEFINITIVE = frozenset({Verdict.TRUE, Verdict.FALSE})
MutantStatus = Literal["killed", "survived", "undecided"]


class PropertyOutcome(DomainModel):
    """What one property said on the original net and on one mutant."""

    property_id: str
    original: Verdict
    mutant: Verdict
    # For a FALSE on the mutant: whether its counterexample replays on the mutant (None: none).
    replays_on_mutant: bool | None = None


class MutantJudgement(DomainModel):
    """The status of one mutant, the properties that killed it, and whether the fault was found."""

    mutant_id: str
    status: MutantStatus
    killers: tuple[str, ...] = ()
    # M6: a property true on the original failed on the mutant with a counterexample that replays.
    fault_found: bool = False


def judge_mutant(*, mutant_id: str, outcomes: tuple[PropertyOutcome, ...]) -> MutantJudgement:
    """Decide whether the properties killed a mutant, left it alive, or could not tell."""
    killers = tuple(
        o.property_id
        for o in outcomes
        if o.original in DEFINITIVE and o.mutant in DEFINITIVE and o.original is not o.mutant
    )
    found = any(
        o.original is Verdict.TRUE and o.mutant is Verdict.FALSE and o.replays_on_mutant is True
        for o in outcomes
    )
    if killers:
        return MutantJudgement(
            mutant_id=mutant_id, status="killed", killers=killers, fault_found=found
        )
    undecided = any(o.original not in DEFINITIVE or o.mutant not in DEFINITIVE for o in outcomes)
    # No property at all can say nothing either way: that is undecided, not survived.
    status: MutantStatus = "undecided" if undecided or not outcomes else "survived"
    return MutantJudgement(mutant_id=mutant_id, status=status, fault_found=found)


class MutationScore(DomainModel):
    """M5 and M6 for one family under one condition."""

    family: str
    mutants: int
    killed: int
    survived: int
    undecided: int
    faults_found: int

    @property
    def score(self) -> float | None:
        """M5: killed over killed and survived; None when no mutant was decided."""
        decided = self.killed + self.survived
        return None if decided == 0 else self.killed / decided

    @property
    def fault_finding(self) -> float | None:
        """M6: the share of mutants whose fault a property found; None without mutants."""
        return None if self.mutants == 0 else self.faults_found / self.mutants


def score_family(*, family: str, judgements: tuple[MutantJudgement, ...]) -> MutationScore:
    """Count the judgements of one family, undecided mutants apart."""
    return MutationScore(
        family=family,
        mutants=len(judgements),
        killed=sum(j.status == "killed" for j in judgements),
        survived=sum(j.status == "survived" for j in judgements),
        undecided=sum(j.status == "undecided" for j in judgements),
        faults_found=sum(j.fault_found for j in judgements),
    )


class ConditionMutation(DomainModel):
    """M5 and M6 for a condition: per family and the mean over the families that have a value."""

    families: tuple[MutationScore, ...]
    mean_score: float | None
    mean_fault_finding: float | None


def score_condition(*, families: tuple[MutationScore, ...]) -> ConditionMutation:
    """Average the families (each counts once, whatever its number of mutants)."""
    scores = [f.score for f in families if f.score is not None]
    findings = [f.fault_finding for f in families if f.fault_finding is not None]
    return ConditionMutation(
        families=tuple(sorted(families, key=lambda f: f.family)),
        mean_score=sum(scores) / len(scores) if scores else None,
        mean_fault_finding=sum(findings) / len(findings) if findings else None,
    )
