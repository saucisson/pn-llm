"""When two engines are interchangeable for a property (docs/equivalence.md).

Engines are *equivalent for a class of properties* when both take part in the contest
examinations the class needs (so they answer the same questions, in the same verdict domain) and
no known difference of meaning separates them. A difference that does not change the verdict
(an atom rewritten into an equivalent one, a missing counterexample) is a caveat; one that can
change it breaks the equivalence and must say for which class.
"""

from __future__ import annotations

from .models import DomainModel, EngineInfo


class Difference(DomainModel):
    """A known difference of behaviour of engines, for some classes of properties."""

    engines: tuple[str, ...]
    # Keys of property classes (``ltl-fireability+next``), or ``*`` for all of them.
    property_classes: tuple[str, ...]
    text: str
    # True when the difference can change a verdict: the engines are then not interchangeable.
    breaks_equivalence: bool


class EquivalenceClass(DomainModel):
    """The engines interchangeable for one class of properties, and what to keep in mind."""

    property_class: str
    engines: tuple[str, ...]
    caveats: tuple[str, ...]


# Every entry is something observed, not feared. The conformance suite (docs/conformance-report.md)
# is where a difference that changes a verdict would show up: it is added here when it does.
KNOWN_DIFFERENCES: tuple[Difference, ...] = (
    Difference(
        engines=("itstools",),
        property_classes=("*",),
        text=(
            "the deadlock atom is written as 'no transition is fireable', which the tool reads; "
            "the meaning is the same"
        ),
        breaks_equivalence=False,
    ),
    Difference(
        engines=("itstools",),
        property_classes=("*",),
        text="gives no counterexample, so a FALSE cannot be checked by replay",
        breaks_equivalence=False,
    ),
    Difference(
        engines=("tapaal",),
        property_classes=("*",),
        text="gives no counterexample on colored nets (it unfolds them)",
        breaks_equivalence=False,
    ),
)


def applies(*, difference: Difference, engine: str, key: str) -> bool:
    """Tell whether a difference concerns an engine for a class."""
    return engine in difference.engines and (
        "*" in difference.property_classes or key in difference.property_classes
    )


def equivalence_table(*, engines: tuple[EngineInfo, ...]) -> tuple[EquivalenceClass, ...]:
    """List, for each class some engine checks, the engines interchangeable for it.

    An engine whose known difference breaks the equivalence for a class is left out of it.
    """
    keys = sorted({key for engine in engines for key in engine.classes})
    table = []
    for key in keys:
        members = [
            engine
            for engine in engines
            if key in engine.classes
            and not any(
                d.breaks_equivalence and applies(difference=d, engine=engine.name, key=key)
                for d in KNOWN_DIFFERENCES
            )
        ]
        caveats = tuple(
            f"{engine.name}: {d.text}"
            for engine in members
            for d in KNOWN_DIFFERENCES
            if applies(difference=d, engine=engine.name, key=key)
        )
        table.append(
            EquivalenceClass(
                property_class=key,
                engines=tuple(sorted(e.name for e in members)),
                caveats=caveats,
            )
        )
    return tuple(table)
