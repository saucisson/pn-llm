"""Run a condition on the families of a frozen split (``python -m app.run_experiment``).

Prints one JSON record per run (docs/evaluation.md). The net of a family is its first stored
P/T instance by name, so every condition sees the same one. The conditions are B0 (rules) and
L1, L2, L3, N (the model). The test families are refused unless the frozen version is named,
because the test set is run once per frozen version.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from app.application.splits import SplitService
from app.domain.errors import InvalidRequestError
from app.domain.experiment import ExperimentBudget, RunSpec
from app.domain.mcc import MccNetType
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_splits import SqliteSplits
from app.main import build_experiments
from app.settings import Settings


def run_main() -> None:
    """Run a condition on each family of a role of a split and print the records."""
    parser = argparse.ArgumentParser(description="Run an evaluation condition.")
    parser.add_argument("--split", required=True)
    parser.add_argument("--role", choices=["dev", "test"], default="dev")
    parser.add_argument("--frozen", metavar="TAG", help="required for the test families")
    parser.add_argument("--condition", choices=["B0", "L1", "L2", "L3", "N"], default="B0")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", default="pn-llm")
    parser.add_argument("--max-properties", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--mutants-per-operator", type=int, default=3)
    arguments = parser.parse_args()
    if arguments.role == "test" and not arguments.frozen:
        raise InvalidRequestError("The test families are run once per frozen version: name it")
    config = Settings()
    split = SplitService(
        splits=SqliteSplits(path=config.database_path),
        catalog=SqliteCatalog(path=config.database_path),
    ).get(name=arguments.split)
    families = sorted(a.family for a in split.assignments if a.role == arguments.role)
    entries = SqliteCatalog(path=config.database_path).entries(family=None, net_type=MccNetType.PT)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - git on the path
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    experiments = build_experiments(config=config)
    for family in families:
        instances = sorted((e for e in entries if e.family == family), key=lambda e: e.instance)
        if not instances:
            sys.stderr.write(f"{family}: no stored P/T instance, skipped\\n")
            continue
        for repetition in range(arguments.repetitions):
            spec = RunSpec(
                condition=arguments.condition,
                family=family,
                repetition=repetition,
                seed=f"{arguments.seed}/{repetition}",
                budget=ExperimentBudget(
                    max_properties=arguments.max_properties,
                    check_timeout_s=arguments.timeout,
                    mutants_per_operator=arguments.mutants_per_operator,
                ),
                git_commit=commit or None,
            )
            try:
                record = (
                    experiments.judge.run_baseline(spec=spec, net_id=instances[0].net_id)
                    if arguments.condition == "B0"
                    else experiments.models.run(spec=spec, net_id=instances[0].net_id)
                )
            except InvalidRequestError as error:
                sys.stderr.write(f"{family}: skipped ({error})\n")
                break
            sys.stdout.write(record.model_dump_json() + "\\n")


if __name__ == "__main__":
    run_main()
