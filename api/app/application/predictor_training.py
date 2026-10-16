"""Use case: train the predictor on the development families of a frozen split, and judge it."""

from __future__ import annotations

from app.domain.errors import InvalidRequestError
from app.domain.models import DomainModel
from app.domain.predictor import Predictor
from app.domain.selection_evaluation import (
    CrossValidation,
    Hyperparameters,
    cross_validate,
    train_predictor,
)

from .ports import ModelCatalogRepository, ResultsRepository, SplitRepository


class TrainingReport(DomainModel):
    """The trained predictor and how its selection did, judged by family folds.

    ``tried`` has the cross-validation of every margin that was tried on the development folds,
    ``validation`` the chosen one; the margin was chosen on those folds, so their score is
    optimistic and only the test families, run once, can confirm it.
    """

    predictor: Predictor
    validation: CrossValidation
    tried: tuple[CrossValidation, ...]
    max_depth: int
    min_leaf: int


class PredictorTrainer:
    """Train on the development families only: the test families are never read."""

    def __init__(
        self,
        *,
        catalog: ModelCatalogRepository,
        results: ResultsRepository,
        splits: SplitRepository,
    ) -> None:
        """Create the trainer over the instance sizes, the published runs and the frozen splits."""
        self._catalog = catalog
        self._results = results
        self._splits = splits

    def train(
        self, *, split_name: str, max_depth: int, min_leaf: int, margins: tuple[float, ...]
    ) -> TrainingReport:
        """Train one tree per engine and examination, choose the margin, cross-validate by family.

        Raises:
            NotFoundError: if the split does not exist.
            InvalidRequestError: if there are no instance sizes or no runs to learn from.
        """
        split = self._splits.load_split(name=split_name)
        sizes = self._catalog.sizes()
        runs = tuple(self._results.instance_runs())
        if not sizes or not runs:
            raise InvalidRequestError(
                "Nothing to learn from: import the results and count the instance sizes first"
            )
        tried = tuple(
            cross_validate(
                runs=runs,
                sizes=sizes,
                split=split,
                hyper=Hyperparameters(max_depth=max_depth, min_leaf=min_leaf, margin=margin),
            )
            for margin in margins
        )
        best = max(tried, key=lambda v: (v.score.selector_solved, -v.margin))
        dev = frozenset(a.family for a in split.assignments if a.role == "dev")
        return TrainingReport(
            predictor=train_predictor(
                runs=runs,
                sizes=sizes,
                families=dev,
                hyper=Hyperparameters(max_depth=max_depth, min_leaf=min_leaf, margin=best.margin),
                trained_on=f"split {split.name}, development families",
            ),
            validation=best,
            tried=tried,
            max_depth=max_depth,
            min_leaf=min_leaf,
        )
