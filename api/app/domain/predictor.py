"""A small learned model of which engine will answer: decision trees over the size of the net.

For each engine and examination a decision tree gives the probability that the engine computes an
answer, from features of the net (docs/equivalence.md). The trees are trained offline on the
contest's published results and loaded by the selector; the platform ships no learning code in the
request path, only the evaluation of a tree. Training is by family (the unit of evaluation,
never the instance) and the test families are not touched while tuning (CLAUDE.md, evaluation
rules).
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from .mcc import MccNetType
from .mcc_results import RunOutcome
from .models import DomainModel

FEATURE_SET = "1"
MIN_GAIN = 1e-9
FEATURE_NAMES = ("log10_places", "log10_transitions", "log10_arcs", "colored")


class InstanceSize(DomainModel):
    """The size of one contest instance, counted on its PNML."""

    instance: str
    family: str
    net_type: MccNetType
    places: int
    transitions: int
    arcs: int


def features_of(*, places: int, transitions: int, arcs: int, colored: bool) -> tuple[float, ...]:
    """The feature vector of a net: sizes on a log scale, and whether it is colored."""
    return (
        math.log10(max(places, 1)),
        math.log10(max(transitions, 1)),
        math.log10(max(arcs, 1)),
        1.0 if colored else 0.0,
    )


class Leaf(DomainModel):
    """For the instances that end here: how often the engine answers, and how fast when it does."""

    kind: Literal["leaf"] = "leaf"
    probability: float = Field(ge=0, le=1)
    runs: int
    # Mean of log10(milliseconds) over the runs that answered; absent when none did.
    mean_log_time: float | None = None


class Split(DomainModel):
    """Go to ``low`` when the feature is at most the threshold, else to ``high``."""

    kind: Literal["split"] = "split"
    feature: int
    threshold: float
    low: Node
    high: Node


type Node = Leaf | Split


class LabelledRun(DomainModel):
    """One training example: the features of an instance, whether the engine answered, how fast."""

    features: tuple[float, ...]
    answered: bool
    log_time: float = 0.0


class EngineTree(DomainModel):
    """The tree of one engine for one examination."""

    tool: str
    examination: str
    runs: int
    tree: Node


class DefaultEngine(DomainModel):
    """The engine that answered most often on an examination in the training data."""

    examination: str
    tool: str


class Predictor(DomainModel):
    """The trees of every engine and examination, with what they were trained on.

    The default engine of an examination is kept unless a tree gives another engine a chance that
    is better by more than ``margin``: with features as coarse as sizes, a small advantage is noise.
    """

    feature_set: str = FEATURE_SET
    trained_on: str
    margin: float = 0.0
    defaults: tuple[DefaultEngine, ...] = ()
    trees: tuple[EngineTree, ...]


def gini(*, positives: int, total: int) -> float:
    """Return the Gini impurity of a set with that many positives."""
    if total == 0:
        return 0.0
    share = positives / total
    return 2 * share * (1 - share)


def grow(*, runs: tuple[LabelledRun, ...], depth: int, max_depth: int, min_leaf: int) -> Node:
    """Grow a tree: split where the impurity falls most, until the data or the depth is spent."""
    positives = sum(r.answered for r in runs)
    times = [r.log_time for r in runs if r.answered]
    leaf = Leaf(
        probability=positives / len(runs) if runs else 0.0,
        runs=len(runs),
        mean_log_time=sum(times) / len(times) if times else None,
    )
    if depth >= max_depth or positives in {0, len(runs)} or len(runs) < 2 * min_leaf:
        return leaf
    best: tuple[float, int, float] | None = None
    base = gini(positives=positives, total=len(runs))
    for feature in range(len(runs[0].features)):
        ordered = sorted(runs, key=lambda r: r.features[feature])
        below = 0
        for index in range(1, len(ordered)):
            below += ordered[index - 1].answered
            if index < min_leaf or len(ordered) - index < min_leaf:
                continue
            if ordered[index - 1].features[feature] == ordered[index].features[feature]:
                continue
            weighted = (
                index * gini(positives=below, total=index)
                + (len(ordered) - index)
                * gini(positives=positives - below, total=len(ordered) - index)
            ) / len(ordered)
            gain = base - weighted
            threshold = (
                ordered[index - 1].features[feature] + ordered[index].features[feature]
            ) / 2
            if gain > MIN_GAIN and (best is None or gain > best[0]):
                best = (gain, feature, threshold)
    if best is None:
        return leaf
    _, feature, threshold = best
    low = tuple(r for r in runs if r.features[feature] <= threshold)
    high = tuple(r for r in runs if r.features[feature] > threshold)
    return Split(
        feature=feature,
        threshold=threshold,
        low=grow(runs=low, depth=depth + 1, max_depth=max_depth, min_leaf=min_leaf),
        high=grow(runs=high, depth=depth + 1, max_depth=max_depth, min_leaf=min_leaf),
    )


def leaf_of(*, tree: Node, features: tuple[float, ...]) -> Leaf:
    """Walk a tree with the features of a net down to its leaf."""
    node = tree
    while isinstance(node, Split):
        node = node.low if features[node.feature] <= node.threshold else node.high
    return node


def probability_of(*, tree: Node, features: tuple[float, ...]) -> float:
    """Return the chance that the engine answers, at the leaf the features lead to."""
    return leaf_of(tree=tree, features=features).probability


def expected_time_s(*, tree: Node, features: tuple[float, ...]) -> float | None:
    """Return the time an answer takes at the leaf the features lead to, in seconds, if known."""
    mean = leaf_of(tree=tree, features=features).mean_log_time
    return None if mean is None else 10**mean / 1000


def is_answer(*, outcome: RunOutcome) -> bool:
    """A run answered when the contest counts it as computed."""
    return outcome is RunOutcome.COMPUTED


Split.model_rebuild()
