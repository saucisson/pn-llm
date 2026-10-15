"""Use cases about the splits of families used by the evaluation."""

from __future__ import annotations

from app.domain.splits import Split, make_split

from .ports import ModelCatalogRepository, SplitRepository


class SplitService:
    """Create and read frozen splits of the contest families."""

    def __init__(self, *, splits: SplitRepository, catalog: ModelCatalogRepository) -> None:
        """Create the service over the split store and the catalog the families come from."""
        self._splits = splits
        self._catalog = catalog

    def create(self, *, name: str, seed: str, folds: int, test_fraction: float) -> Split:
        """Split every family of the catalog and freeze the result under ``name``.

        Raises:
            ConflictError: if the name is taken (a split is never replaced).
            InvalidRequestError: if there are too few families for the folds.
        """
        split = make_split(
            name=name,
            seed=seed,
            folds=folds,
            test_fraction=test_fraction,
            families=tuple(family.name for family in self._catalog.families()),
        )
        self._splits.save_split(split=split)
        return split

    def get(self, *, name: str) -> Split:
        """Return a split, or raise NotFoundError."""
        return self._splits.load_split(name=name)

    def names(self) -> tuple[str, ...]:
        """Return the names of the stored splits."""
        return self._splits.split_names()
