"""Train the predictor (``python -m app.train_predictor --split NAME --out model.json``).

Reads the imported contest results and instance sizes from the database, trains on the development
families of a frozen split, prints how its selection did in family folds against the single best and
the virtual best engine, and writes the model for ``PNVERIF_PREDICTOR_PATH``. The test families are
not read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.application.predictor_training import PredictorTrainer
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_results import SqliteResults
from app.infrastructure.sqlite_splits import SqliteSplits
from app.settings import Settings


def train_main() -> None:
    """Train, write the model and print the report."""
    parser = argparse.ArgumentParser(description="Train the engine predictor.")
    parser.add_argument("--split", required=True, help="name of a frozen split of the families")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--min-leaf", type=int, default=20)
    parser.add_argument(
        "--margins",
        type=float,
        nargs="+",
        default=[0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0],
        help="advantages over the default engine to try; the best on the development folds is kept",
    )
    arguments = parser.parse_args()
    config = Settings()
    report = PredictorTrainer(
        catalog=SqliteCatalog(path=config.database_path),
        results=SqliteResults(path=config.database_path),
        splits=SqliteSplits(path=config.database_path),
    ).train(
        split_name=arguments.split,
        max_depth=arguments.max_depth,
        min_leaf=arguments.min_leaf,
        margins=tuple(arguments.margins),
    )
    arguments.out.write_text(report.predictor.model_dump_json(indent=1) + "\n")
    sys.stdout.write(report.validation.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    train_main()
