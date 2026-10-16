"""Write the manifest of a frozen evaluation (``python -m app.freeze --name eval-freeze-1``).

Describes the families (development and test, public, unpublished and synthetic), the selection
rule, the thresholds, the code version and the engines. It writes the file and prints the git
command that tags the commit holding it: the tag is yours to create once the manifest is committed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from pydantic import TypeAdapter

from app.application.splits import SplitService
from app.domain.freeze import ExtraFamily, FrozenVersion, build_manifest
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_splits import SqliteSplits
from app.settings import Settings


def freeze_main() -> None:
    """Build the manifest from the stored split and write it."""
    parser = argparse.ArgumentParser(description="Describe a frozen evaluation.")
    parser.add_argument("--name", required=True, help="the tag to create, such as eval-freeze-1")
    parser.add_argument("--split", required=True)
    parser.add_argument("--extra", type=Path, help="JSON list of unpublished/synthetic families")
    parser.add_argument("--protocol", type=Path, default=Path("docs/evaluation.md"))
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    config = Settings()
    split = SplitService(
        splits=SqliteSplits(path=config.database_path),
        catalog=SqliteCatalog(path=config.database_path),
    ).get(name=arguments.split)
    extras = (
        ()
        if arguments.extra is None
        else TypeAdapter(tuple[ExtraFamily, ...]).validate_json(arguments.extra.read_text())
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - git on the path
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    engines = EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner()).list_engines()
    manifest = build_manifest(
        name=arguments.name,
        split=split,
        extras=extras,
        git_commit=commit,
        protocol_text=arguments.protocol.read_text(),
        engines=tuple(FrozenVersion(name=e.name, version=e.version) for e in engines),
    )
    arguments.out.write_text(manifest.model_dump_json(indent=1) + "\n")
    sys.stdout.write(
        f"Wrote {arguments.out}. Commit it, then tag that commit:\n"
        f"  git tag -a {arguments.name} -m 'Frozen evaluation {arguments.name}'\n"
    )


if __name__ == "__main__":
    freeze_main()
