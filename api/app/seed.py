"""Seed the platform with Model Checking Contest models (``python -m app.seed``).

Nothing downloaded is versioned: files go to ``PNVERIF_MCC_DIRECTORY`` and the nets to the
database. Run it again to resume; what is already stored is left as is.
"""

from __future__ import annotations

import argparse
import sys

from app.application.models import ModelCatalogService
from app.application.nets import NetService
from app.application.results import ResultsService
from app.application.splits import SplitService
from app.infrastructure.json_logging import configure_logging
from app.infrastructure.mcc_source import MccDirectory
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_results import SqliteResults
from app.infrastructure.sqlite_splits import SqliteSplits
from app.infrastructure.sqlite_store import SqliteStore
from app.settings import Settings


def seed_main() -> None:
    """Download and store families, results or a split, then print the outcome as JSON."""
    parser = argparse.ArgumentParser(description="Seed the platform with contest models.")
    parser.add_argument("families", nargs="*", help="family names (default: all of them)")
    parser.add_argument("--max-nets-per-family", type=int, default=None)
    parser.add_argument(
        "--results-only",
        action="store_true",
        help="store the published results (about 5 MB) of the contest year and stop",
    )
    parser.add_argument(
        "--split",
        metavar="NAME",
        help="freeze a split of the stored families into folds and a test set under this name",
    )
    parser.add_argument("--split-seed", default="pn-llm")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument(
        "--properties",
        action="store_true",
        help="read the contest inputs (about 1 GB) to store the formulas of each examination too",
    )
    arguments = parser.parse_args()

    config = Settings()
    configure_logging(level=config.log_level, as_json=config.log_json)
    store = SqliteStore(path=config.database_path)
    service = ModelCatalogService(
        catalog=SqliteCatalog(path=config.database_path),
        nets=NetService(
            nets=store,
            max_upload_bytes=config.mcc_max_net_bytes,
            limits=config.document_limits(),
        ),
        descriptions=store,
    )
    source = MccDirectory(directory=config.mcc_directory, base_url=config.mcc_base_url)
    if arguments.results_only:
        stored = ResultsService(results=SqliteResults(path=config.database_path)).import_results(
            source=source, year=config.mcc_year
        )
        sys.stdout.write(stored.model_dump_json(indent=2) + "\n")
        return
    if arguments.split:
        split = SplitService(
            splits=SqliteSplits(path=config.database_path),
            catalog=SqliteCatalog(path=config.database_path),
        ).create(
            name=arguments.split,
            seed=arguments.split_seed,
            folds=arguments.folds,
            test_fraction=arguments.test_fraction,
        )
        sys.stdout.write(split.model_dump_json(indent=2) + "\n")
        return
    report = service.seed(
        source=source,
        only_families=tuple(arguments.families),
        max_nets_per_family=arguments.max_nets_per_family,
        with_properties=arguments.properties,
    )
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    seed_main()
