"""Blind expert rating of properties (measure M8, docs/evaluation.md).

Raters see properties without knowing which condition wrote them: the sheet holds the property in
one canonical text form, in an order shuffled from a seed, with an item id that carries nothing.
The key that maps items back to conditions is kept apart and used only to analyse the ratings.
A property that two conditions wrote identically is rated once. The sheet leaves out the
proposer's gloss: its wording would give the condition away (the baseline's glosses are templates).
"""

from __future__ import annotations

import hashlib
import random
from typing import Literal

from pydantic import Field

from .analysis_stats import FamilyValue
from .experiment import RunRecord
from .formula_text import render_text
from .models import DomainModel


class RatingItem(DomainModel):
    """What a rater sees: a property about a net, and nothing about where it comes from."""

    item_id: str
    family: str
    net_id: str
    logic: Literal["ltl", "ctl", "state"]
    text: str


class ItemSource(DomainModel):
    """Where an item came from, kept out of the sheet."""

    condition: str
    repetition: int


class RatingKey(DomainModel):
    """The hidden side of an item: every condition that wrote it."""

    item_id: str
    sources: tuple[ItemSource, ...]


class RatingSheet(DomainModel):
    """The items to give to raters, and the key to keep away from them."""

    items: tuple[RatingItem, ...]
    key: tuple[RatingKey, ...]


class Rating(DomainModel):
    """One rater's judgement of one item: how relevant (1 to 5) and whether to keep it."""

    item_id: str
    rater: str
    score: int = Field(ge=1, le=5)
    keep: bool


def build_sheet(*, records: tuple[RunRecord, ...], per_family: int, seed: str) -> RatingSheet:
    """Pool the properties of all conditions per family, dedupe them and draw ``per_family``.

    The draw is uniform over distinct properties, so a condition that proposes more properties
    is not favoured by the sheet beyond what it proposed.
    """
    found: dict[tuple[str, str, str, str], list[ItemSource]] = {}
    for record in records:
        for measured in record.properties:
            formula = measured.formula
            text = render_text(expression=formula.ast)
            key = (record.spec.family, record.net_id, formula.logic, text)
            sources = found.setdefault(key, [])
            source = ItemSource(condition=record.spec.condition, repetition=record.spec.repetition)
            if source not in sources:
                sources.append(source)
    items: list[RatingItem] = []
    keys: list[RatingKey] = []
    for family in sorted({k[0] for k in found}):
        distinct = sorted(k for k in found if k[0] == family)
        rng = random.Random(f"{seed}/{family}")  # noqa: S311 - reproducible draw
        for _, net_id, logic, text in rng.sample(distinct, k=min(per_family, len(distinct))):
            item_id = hashlib.sha256(
                f"{seed}|{family}|{net_id}|{logic}|{text}".encode()
            ).hexdigest()[:10]
            items.append(
                RatingItem(item_id=item_id, family=family, net_id=net_id, logic=logic, text=text)
            )
            keys.append(
                RatingKey(
                    item_id=item_id,
                    sources=tuple(
                        sorted(
                            found[(family, net_id, logic, text)],
                            key=lambda s: (s.condition, s.repetition),
                        )
                    ),
                )
            )
    order = random.Random(f"{seed}/order")  # noqa: S311 - reproducible shuffle
    order.shuffle(items)
    return RatingSheet(items=tuple(items), key=tuple(sorted(keys, key=lambda k: k.item_id)))


class Agreement(DomainModel):
    """How two raters agree on the items both rated."""

    rater_a: str
    rater_b: str
    items: int
    keep_kappa: float | None
    score_weighted_kappa: float | None


def kappa(
    *, a: tuple[int, ...], b: tuple[int, ...], categories: tuple[int, ...], weighted: bool
) -> float | None:
    """Return Cohen's kappa of two label lists, linearly weighted by distance when asked.

    None when chance agreement is total (no variation to agree on).
    """
    n = len(a)
    if n == 0:
        return None
    span = max(categories) - min(categories) or 1

    def disagreement(*, x: int, y: int) -> float:
        return abs(x - y) / span if weighted else float(x != y)

    observed = sum(disagreement(x=x, y=y) for x, y in zip(a, b, strict=True)) / n
    expected = sum(
        (a.count(x) / n) * (b.count(y) / n) * disagreement(x=x, y=y)
        for x in categories
        for y in categories
    )
    return None if expected == 0 else 1 - observed / expected


def agreements(*, ratings: tuple[Rating, ...]) -> tuple[Agreement, ...]:
    """Report the agreement of every pair of raters on the items both rated."""
    raters = sorted({r.rater for r in ratings})
    found = []
    for index, first in enumerate(raters):
        for second in raters[index + 1 :]:
            of_first = {r.item_id: r for r in ratings if r.rater == first}
            of_second = {r.item_id: r for r in ratings if r.rater == second}
            shared = sorted(of_first.keys() & of_second.keys())
            found.append(
                Agreement(
                    rater_a=first,
                    rater_b=second,
                    items=len(shared),
                    keep_kappa=kappa(
                        a=tuple(int(of_first[i].keep) for i in shared),
                        b=tuple(int(of_second[i].keep) for i in shared),
                        categories=(0, 1),
                        weighted=False,
                    ),
                    score_weighted_kappa=kappa(
                        a=tuple(of_first[i].score for i in shared),
                        b=tuple(of_second[i].score for i in shared),
                        categories=(1, 2, 3, 4, 5),
                        weighted=True,
                    ),
                )
            )
    return tuple(found)


def rating_values(*, sheet: RatingSheet, ratings: tuple[Rating, ...]) -> tuple[FamilyValue, ...]:
    """Turn ratings into per-condition, per-family values for the analysis (M8).

    Every condition that wrote an item gets its rating; raters are averaged per item first, then
    items per family.
    """
    family_of = {i.item_id: i.family for i in sheet.items}
    sources_of = {k.item_id: k.sources for k in sheet.key}
    per_item: dict[str, list[Rating]] = {}
    for rating in ratings:
        per_item.setdefault(rating.item_id, []).append(rating)
    pooled: dict[tuple[str, str, str], list[float]] = {}
    for item_id, given in per_item.items():
        for source in sources_of.get(item_id, ()):
            family = family_of[item_id]
            pooled.setdefault((source.condition, family, "M8_rating"), []).append(
                sum(r.score for r in given) / len(given)
            )
            pooled.setdefault((source.condition, family, "M8_keep"), []).append(
                sum(r.keep for r in given) / len(given)
            )
    return tuple(
        FamilyValue(condition=c, family=f, measure=m, value=sum(v) / len(v))
        for (c, f, m), v in sorted(pooled.items())
    )
