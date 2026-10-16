"""The frozen description of an evaluation: families, rule, thresholds and versions (E3).

Freezing writes down, before the test run, which families are for development and which for the
test, how they were chosen, which of them are public contest models and which are unpublished or
synthetic (reported separately because public models may be in a model's training data), the
thresholds, and the versions of the code and the engines. The manifest is committed and a git tag
``eval-freeze-N`` points at that commit; anything changed afterwards is a deviation to report.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from .evaluation_report import NON_TRIVIAL_MIN, PRIMARY_MIN_GAIN
from .models import DomainModel
from .splits import Role, Split

Provenance = Literal["public", "unpublished", "synthetic"]


class ExtraFamily(DomainModel):
    """A family that is not a contest model, assigned to a role by the author, with its nets."""

    family: str
    provenance: Literal["unpublished", "synthetic"]
    role: Role
    net_ids: tuple[str, ...]


class FrozenFamily(DomainModel):
    """A family of the frozen evaluation and where it comes from."""

    family: str
    role: Role
    provenance: Provenance
    fold: int | None = None


class FrozenVersion(DomainModel):
    """A tool and the version the evaluation will run with."""

    name: str
    version: str


class FreezeManifest(DomainModel):
    """Everything the test run is bound to."""

    name: str
    split: str
    split_seed: str
    selection_rule: str
    families: tuple[FrozenFamily, ...]
    thresholds: tuple[str, ...]
    git_commit: str
    protocol_sha256: str
    engines: tuple[FrozenVersion, ...]


def build_manifest(
    *,
    name: str,
    split: Split,
    extras: tuple[ExtraFamily, ...],
    git_commit: str,
    protocol_text: str,
    engines: tuple[FrozenVersion, ...],
) -> FreezeManifest:
    """Describe the evaluation as it is frozen.

    Raises:
        ValueError: if an extra family reuses the name of a contest family.
    """
    contest = {a.family for a in split.assignments}
    clash = sorted(contest & {e.family for e in extras})
    if clash:
        raise ValueError(f"Extra families share a name with contest families: {', '.join(clash)}")
    families = (
        *(
            FrozenFamily(family=a.family, role=a.role, provenance="public", fold=a.fold)
            for a in split.assignments
        ),
        *(FrozenFamily(family=e.family, role=e.role, provenance=e.provenance) for e in extras),
    )
    return FreezeManifest(
        name=name,
        split=split.name,
        split_seed=split.seed,
        selection_rule=(
            f"contest families ranked by sha256(seed|purpose|family) with seed {split.seed!r}; "
            f"{split.test_fraction:.0%} held out as the test set, the rest in {split.folds} "
            "development folds; unpublished and synthetic families are assigned by the author "
            "and reported separately"
        ),
        families=tuple(sorted(families, key=lambda f: (f.role, f.family))),
        thresholds=(
            "C1: 0 unsupported verdicts",
            f"C3: M6 of L3 minus B0 at least +{PRIMARY_MIN_GAIN:.2f}, 95% interval above 0",
            f"M4: at least {NON_TRIVIAL_MIN:.0%} non-trivial",
        ),
        git_commit=git_commit,
        protocol_sha256=hashlib.sha256(protocol_text.encode()).hexdigest(),
        engines=engines,
    )
