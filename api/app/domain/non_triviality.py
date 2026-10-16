"""Measure M4: the share of properties that say something about the behaviour.

A property is trivial when the structure of the net alone decides it (a bound, an invariant, a dead
transition) or when an implication has an impossible premise. The findings are the product's own
(``triviality.triviality_of``, the ones the assistant is shown): the measure counts them and does
not redo them. Families are aggregated first and the condition is the mean over families, as the
protocol asks (docs/evaluation.md).
"""

from __future__ import annotations

from .models import DomainModel
from .triviality import Triviality


class PropertyFindings(DomainModel):
    """What the structure says of one property; empty when it decides nothing."""

    property_id: str
    findings: tuple[Triviality, ...]


class PropertySet(DomainModel):
    """The properties one condition produced for one net, and what the structure says of them."""

    condition: str
    family: str
    property_ids: tuple[str, ...]
    findings: tuple[PropertyFindings, ...] = ()


class FamilyNonTriviality(DomainModel):
    """The counts for one family under one condition."""

    family: str
    properties: int
    vacuous: int
    decided_by_structure: int
    non_trivial: int

    @property
    def share(self) -> float | None:
        """Return the share of non-trivial properties, or None for a family without properties."""
        return None if self.properties == 0 else self.non_trivial / self.properties


class ConditionNonTriviality(DomainModel):
    """M4 for one condition: per family, and the mean over families."""

    condition: str
    families: tuple[FamilyNonTriviality, ...]
    mean_share: float | None


def score_property_set(*, property_set: PropertySet) -> FamilyNonTriviality:
    """Count the vacuous, structure-decided and non-trivial properties of one set.

    A property with both a vacuous premise and a structural verdict counts once in each of the
    first two columns and once as trivial.
    """
    vacuous = decided = trivial = 0
    for property_id in property_set.property_ids:
        kinds = {
            f.kind
            for item in property_set.findings
            if item.property_id == property_id
            for f in item.findings
        }
        is_vacuous = "vacuous_antecedent" in kinds
        is_decided = bool(kinds & {"holds_in_every_state", "holds_in_no_state"})
        vacuous += is_vacuous
        decided += is_decided
        trivial += is_vacuous or is_decided
    total = len(property_set.property_ids)
    return FamilyNonTriviality(
        family=property_set.family,
        properties=total,
        vacuous=vacuous,
        decided_by_structure=decided,
        non_trivial=total - trivial,
    )


def non_triviality_by_condition(
    *, sets: tuple[PropertySet, ...]
) -> tuple[ConditionNonTriviality, ...]:
    """Return M4 for each condition, conditions in alphabetical order.

    The properties of a family are pooled across its nets first; a family without any property
    adds no share to the mean (it is listed, with no share, so the gap is visible).
    """
    scored = [(s.condition, score_property_set(property_set=s)) for s in sets]
    results = []
    for condition in sorted({c for c, _ in scored}):
        pooled: dict[str, list[FamilyNonTriviality]] = {}
        for name, item in scored:
            if name == condition:
                pooled.setdefault(item.family, []).append(item)
        families = tuple(
            FamilyNonTriviality(
                family=family,
                properties=sum(i.properties for i in items),
                vacuous=sum(i.vacuous for i in items),
                decided_by_structure=sum(i.decided_by_structure for i in items),
                non_trivial=sum(i.non_trivial for i in items),
            )
            for family, items in sorted(pooled.items())
        )
        shares = [f.share for f in families if f.share is not None]
        results.append(
            ConditionNonTriviality(
                condition=condition,
                families=families,
                mean_share=sum(shares) / len(shares) if shares else None,
            )
        )
    return tuple(results)
