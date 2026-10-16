"""Analyze experiment records (``python -m app.analyze_runs RUNS.jsonl ...``).

Reads the records printed by ``app.run_experiment`` and prints the analysis of the protocol as
JSON: the primary outcome (M6 of L3 against B0, paired by family), the secondary comparisons with
Holm's correction, and the values of every family. The same script serves dev and test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.domain.analysis_stats import analyze_runs
from app.domain.experiment import RunRecord


def analyze_main() -> None:
    """Read the records, analyze them by family and print the result."""
    parser = argparse.ArgumentParser(description="Analyze experiment records by family.")
    parser.add_argument("records", nargs="+", type=Path, help="JSON lines of run records")
    parser.add_argument("--seed", default="pn-llm", help="seed of the bootstrap")
    arguments = parser.parse_args()
    records = tuple(
        RunRecord.model_validate_json(line)
        for path in arguments.records
        for line in path.read_text().splitlines()
        if line.strip()
    )
    analysis = analyze_runs(records=records, seed=arguments.seed)
    sys.stdout.write(analysis.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    analyze_main()
