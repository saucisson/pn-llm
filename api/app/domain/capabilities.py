"""What an engine can be asked: the classes of properties, and how they map to contest categories.

A formula belongs to a *property class*: its logic, what its atoms count, and whether it uses the
neXt operator (which makes LTL and CTL sensitive to stuttering, so some reductions are not allowed).
An engine declares the contest examinations it takes part in; it can check a class when it takes
part in every examination the class needs (docs/mcc-tools.md).
"""

from __future__ import annotations

from typing import Literal

from .formula import (
    Compare,
    CtlUnary,
    Enabled,
    Formula,
    Logic,
    LtlUnary,
    Tokens,
    subexpressions,
)
from .models import DomainModel, EngineInfo

Atoms = Literal["cardinality", "fireability", "mixed", "none"]

LOGIC_FAMILY: dict[Logic, str] = {"state": "Reachability", "ctl": "CTL", "ltl": "LTL"}
CATEGORIES = ("Cardinality", "Fireability")


class PropertyClass(DomainModel):
    """The kind of question a formula asks."""

    logic: Logic
    atoms: Atoms
    uses_next: bool

    @property
    def key(self) -> str:
        """A short stable name, such as ``ltl-fireability+next``."""
        return f"{self.logic}-{self.atoms}" + ("+next" if self.uses_next else "")


def property_class_of(*, formula: Formula) -> PropertyClass:
    """Classify a formula by its logic, the atoms it uses and whether it uses neXt."""
    parts = tuple(located.expression for located in subexpressions(expression=formula.ast, path=""))
    cardinality = any(isinstance(p, Tokens | Compare) for p in parts)
    fireability = any(isinstance(p, Enabled) for p in parts)
    atoms: Atoms = (
        "mixed"
        if cardinality and fireability
        else "cardinality"
        if cardinality
        else "fireability"
        if fireability
        else "none"
    )
    uses_next = any(
        (isinstance(p, LtlUnary) and p.op == "X")
        or (isinstance(p, CtlUnary) and p.op in {"AX", "EX"})
        for p in parts
    )
    return PropertyClass(logic=formula.logic, atoms=atoms, uses_next=uses_next)


def examinations_needed(*, property_class: PropertyClass) -> tuple[tuple[str, ...], ...]:
    """List what an engine must take part in to check a class: all of one group of examinations.

    Returned as alternatives: an engine suffices if it takes part in every examination of at
    least one alternative. Mixed atoms need both categories; a formula with no atom (a deadlock
    question) is satisfied by either category.
    """
    family = LOGIC_FAMILY[property_class.logic]
    if property_class.atoms == "mixed":
        return (tuple(family + category for category in CATEGORIES),)
    if property_class.atoms == "none":
        return tuple((family + category,) for category in CATEGORIES)
    return ((family + property_class.atoms.capitalize(),),)


def can_check(*, examinations: tuple[str, ...], property_class: PropertyClass) -> bool:
    """Tell whether an engine taking part in these examinations can check a class."""
    return any(
        all(needed in examinations for needed in alternative)
        for alternative in examinations_needed(property_class=property_class)
    )


def all_classes() -> tuple[PropertyClass, ...]:
    """Every class a formula can belong to (mixed atoms and no atoms included)."""
    return tuple(
        PropertyClass(logic=logic, atoms=atoms, uses_next=uses_next)
        for logic in ("state", "ctl", "ltl")
        for atoms in ("cardinality", "fireability", "mixed", "none")
        for uses_next in ((False,) if logic == "state" else (False, True))
    )


def classes_checked_by(*, examinations: tuple[str, ...]) -> tuple[str, ...]:
    """List the keys of the classes an engine can check."""
    return tuple(
        c.key for c in all_classes() if can_check(examinations=examinations, property_class=c)
    )


class CapabilityRow(DomainModel):
    """Which engines can check one class of properties."""

    property_class: str
    engines: tuple[str, ...]
    colored_engines: tuple[str, ...]


def capability_table(*, engines: tuple[EngineInfo, ...]) -> tuple[CapabilityRow, ...]:
    """List, for every class, the engines that declare they can check it."""
    return tuple(
        CapabilityRow(
            property_class=c.key,
            engines=tuple(sorted(e.name for e in engines if c.key in e.classes)),
            colored_engines=tuple(
                sorted(e.name for e in engines if c.key in e.classes and e.supports_colored)
            ),
        )
        for c in all_classes()
    )
