"""Seed the platform with Model Checking Contest models (``python -m app.seed``).

Nothing downloaded is versioned: files go to ``PNVERIF_MCC_DIRECTORY`` and the nets to the
database. Run it again to resume; what is already stored is left as is.
"""

from __future__ import annotations

import argparse
import sys

from app.application.models import ModelCatalogService
from app.application.nets import NetService
from app.infrastructure.json_logging import configure_logging
from app.infrastructure.mcc_source import MccDirectory
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_store import SqliteStore
from app.settings import Settings


def seed_main() -> None:
    """Download and store the chosen families, then print the report as JSON."""
    parser = argparse.ArgumentParser(description="Seed the platform with contest models.")
    parser.add_argument("families", nargs="*", help="family names (default: all of them)")
    parser.add_argument("--max-nets-per-family", type=int, default=None)
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
    report = service.seed(
        source=MccDirectory(directory=config.mcc_directory, base_url=config.mcc_base_url),
        only_families=tuple(arguments.families),
        max_nets_per_family=arguments.max_nets_per_family,
        with_properties=arguments.properties,
    )
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    seed_main()
