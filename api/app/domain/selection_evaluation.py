"""Training the predictor and judging the selection it makes, with the family as the unit.

Everything here is deterministic. Folds come from a frozen split of the families, so no instance
of a family is ever tested by a model that trained on another instance of it; the held-out test
families are not read at all (they are run once per frozen version, docs/evaluation.md). The
selector
is compared with the single best engine (chosen on the training families) and with the virtual best
(an oracle that picks, for each instance, an engine that answered).
"""

from __future__ import annotations

import math
from collections import defaultdict

from .models import DomainModel
from .predictor import (
    DefaultEngine,
    EngineTree,
    InstanceSize,
    LabelledRun,
    Predictor,
    features_of,
    grow,
    probability_of,
)
from .splits import Split

TIMEOUT_MS = 3_600_000
PENALTY = 2  # PAR-2: a run that did not answer costs twice the timeout


class Hyperparameters(DomainModel):
    """How the trees grow, and how much better another engine must look to replace the default."""

    max_depth: int
    min_leaf: int
    margin: float


class InstanceRun(DomainModel):
    """One published run of an engine on an instance, reduced to what the selection needs."""

    instance: str
    family: str
    tool: str
    examination: str
    answered: bool
    time_ms: float


class FamilyScore(DomainModel):
    """How the choices did on the instances of one family."""

    family: str
    questions: int
    selector: int
    single_best: int
    virtual_best: int


class SelectionScore(DomainModel):
    """How a way of choosing an engine did over a set of questions (instance, examination)."""

    questions: int
    selector_solved: int
    single_best_solved: int
    virtual_best_solved: int
    selector_par2_s: float
    single_best_par2_s: float
    virtual_best_par2_s: float
    by_family: tuple[FamilyScore, ...]


class CrossValidation(DomainModel):
    """The selection judged by leaving each development fold out in turn."""

    margin: float
    folds: int
    score: SelectionScore
    trained_on: str


def key_runs(
    *, runs: tuple[InstanceRun, ...], families: frozenset[str]
) -> dict[tuple[str, str], dict[str, InstanceRun]]:
    """Group the runs of some families by question (instance, examination), then by engine."""
    grouped: dict[tuple[str, str], dict[str, InstanceRun]] = defaultdict(dict)
    for run in runs:
        if run.family in families:
            grouped[(run.instance, run.examination)][run.tool] = run
    return grouped


def train_predictor(
    *,
    runs: tuple[InstanceRun, ...],
    sizes: tuple[InstanceSize, ...],
    families: frozenset[str],
    hyper: Hyperparameters,
    trained_on: str,
) -> Predictor:
    """Train one tree per engine and examination on the runs of some families.

    Only engines that answered at least once on an examination get a tree for it: the others did
    not take part (the published results list them with no answer).
    """
    size_of = {s.instance: s for s in sizes}
    examples: dict[tuple[str, str], list[LabelledRun]] = defaultdict(list)
    for run in runs:
        size = size_of.get(run.instance)
        if run.family not in families or size is None:
            continue
        examples[(run.tool, run.examination)].append(
            LabelledRun(
                features=features_of(
                    places=size.places,
                    transitions=size.transitions,
                    arcs=size.arcs,
                    colored=size.net_type.value == "colored",
                ),
                answered=run.answered,
                log_time=math.log10(max(run.time_ms, 1.0)),
            )
        )
    answered: dict[tuple[str, str], int] = defaultdict(int)
    for run in runs:
        if run.family in families and run.answered:
            answered[(run.examination, run.tool)] += 1
    defaults: dict[str, str] = {}
    for (examination, tool), count in sorted(answered.items()):
        if examination not in defaults or count > answered[(examination, defaults[examination])]:
            defaults[examination] = tool
    return Predictor(
        trained_on=trained_on,
        margin=hyper.margin,
        defaults=tuple(DefaultEngine(examination=e, tool=t) for e, t in sorted(defaults.items())),
        trees=tuple(
            EngineTree(
                tool=tool,
                examination=examination,
                runs=len(data),
                tree=grow(
                    runs=tuple(data), depth=0, max_depth=hyper.max_depth, min_leaf=hyper.min_leaf
                ),
            )
            for (tool, examination), data in sorted(examples.items())
            if answered[(examination, tool)] > 0
        ),
    )


def pick(
    *, predictor: Predictor, features: tuple[float, ...], examination: str, tools: list[str]
) -> str | None:
    """Choose, among the engines that can answer, the one the trees give the best chance.

    The default engine of the examination is kept unless another one has a chance better by more
    than the predictor's margin: with features as coarse as sizes, a small advantage is noise.
    None when no tree covers any of the engines.
    """
    chances = {
        tree.tool: probability_of(tree=tree.tree, features=features)
        for tree in predictor.trees
        if tree.examination == examination and tree.tool in tools
    }
    if not chances:
        return None
    best = min(chances, key=lambda tool: (-chances[tool], tool))
    default = next((d.tool for d in predictor.defaults if d.examination == examination), None)
    if default in chances and chances[best] - chances[default] <= predictor.margin:
        return default
    return best


def score_selection(
    *,
    predictor: Predictor,
    train_runs: tuple[InstanceRun, ...],
    test_runs: dict[tuple[str, str], dict[str, InstanceRun]],
    sizes: tuple[InstanceSize, ...],
    train_families: frozenset[str],
) -> SelectionScore:
    """Judge the selector on held-out questions against the single best and the virtual best.

    The single best engine of an examination is the one that answered most often on the training
    families. A question counts only if at least two engines ran on it.
    """
    size_of = {s.instance: s for s in sizes}
    entered = {(t.examination, t.tool) for t in predictor.trees}
    solved_in_training: dict[tuple[str, str], int] = defaultdict(int)
    for run in train_runs:
        if run.family in train_families and run.answered:
            solved_in_training[(run.examination, run.tool)] += 1
    per_family: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    par2 = [0.0, 0.0, 0.0]
    for (instance, examination), all_tools in sorted(test_runs.items()):
        by_tool = {t: r for t, r in all_tools.items() if (examination, t) in entered}
        size = size_of.get(instance)
        if size is None or len(by_tool) < 2:  # noqa: PLR2004 - a choice needs two engines
            continue
        features = features_of(
            places=size.places,
            transitions=size.transitions,
            arcs=size.arcs,
            colored=size.net_type.value == "colored",
        )
        chosen = pick(
            predictor=predictor, features=features, examination=examination, tools=sorted(by_tool)
        ) or min(by_tool)
        single = max(by_tool, key=lambda t: (solved_in_training[(examination, t)], t))
        runs = list(by_tool.values())
        best = min(runs, key=lambda r: (not r.answered, r.time_ms if r.answered else 0.0, r.tool))
        cost = [
            by_tool[tool].time_ms if by_tool[tool].answered else PENALTY * TIMEOUT_MS
            for tool in (chosen, single)
        ] + [best.time_ms if best.answered else PENALTY * TIMEOUT_MS]
        for index, value in enumerate(cost):
            par2[index] += value
        counts = per_family[by_tool[chosen].family]
        counts[0] += 1
        counts[1] += by_tool[chosen].answered
        counts[2] += by_tool[single].answered
        counts[3] += best.answered
    totals = [sum(c[i] for c in per_family.values()) for i in range(4)]
    questions = totals[0]
    return SelectionScore(
        questions=questions,
        selector_solved=totals[1],
        single_best_solved=totals[2],
        virtual_best_solved=totals[3],
        selector_par2_s=par2[0] / 1000 / max(questions, 1),
        single_best_par2_s=par2[1] / 1000 / max(questions, 1),
        virtual_best_par2_s=par2[2] / 1000 / max(questions, 1),
        by_family=tuple(
            FamilyScore(
                family=family,
                questions=c[0],
                selector=c[1],
                single_best=c[2],
                virtual_best=c[3],
            )
            for family, c in sorted(per_family.items())
        ),
    )


def cross_validate(
    *,
    runs: tuple[InstanceRun, ...],
    sizes: tuple[InstanceSize, ...],
    split: Split,
    hyper: Hyperparameters,
) -> CrossValidation:
    """Leave each development fold out, train on the others, judge on it; the test set is unread."""
    fold_of = {
        a.family: a.fold for a in split.assignments if a.role == "dev" and a.fold is not None
    }
    scores: list[SelectionScore] = []
    for fold in range(split.folds):
        train_families = frozenset(f for f, k in fold_of.items() if k != fold)
        test_families = frozenset(f for f, k in fold_of.items() if k == fold)
        predictor = train_predictor(
            runs=runs,
            sizes=sizes,
            families=train_families,
            hyper=hyper,
            trained_on=f"{split.name} without fold {fold}",
        )
        scores.append(
            score_selection(
                predictor=predictor,
                train_runs=runs,
                test_runs=key_runs(runs=runs, families=test_families),
                sizes=sizes,
                train_families=train_families,
            )
        )
    by_family = tuple(f for s in scores for f in s.by_family)
    return CrossValidation(
        margin=hyper.margin,
        folds=split.folds,
        trained_on=split.name,
        score=SelectionScore(
            questions=sum(s.questions for s in scores),
            selector_solved=sum(s.selector_solved for s in scores),
            single_best_solved=sum(s.single_best_solved for s in scores),
            virtual_best_solved=sum(s.virtual_best_solved for s in scores),
            selector_par2_s=sum(s.selector_par2_s * s.questions for s in scores)
            / max(sum(s.questions for s in scores), 1),
            single_best_par2_s=sum(s.single_best_par2_s * s.questions for s in scores)
            / max(sum(s.questions for s in scores), 1),
            virtual_best_par2_s=sum(s.virtual_best_par2_s * s.questions for s in scores)
            / max(sum(s.questions for s in scores), 1),
            by_family=by_family,
        ),
    )
