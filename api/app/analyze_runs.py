"""Analyze experiment records (``python -m app.analyze_runs RUNS.jsonl ...``).

Reads the records printed by ``app.run_experiment`` and prints the analysis of the protocol as
JSON: the primary outcome (M6 of L3 against B0, paired by family), the secondary comparisons with
Holm's correction, and the values of every family. The same script serves dev and test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.domain.analysis_stats import FamilyProvenance, analyze_runs
from app.domain.experiment import RunRecord
from app.domain.freeze import FreezeManifest


def analyze_main() -> None:
    """Read the records, analyze them by family and print the result."""
    parser = argparse.ArgumentParser(description="Analyze experiment records by family.")
    parser.add_argument("records", nargs="+", type=Path, help="JSON lines of run records")
    parser.add_argument("--seed", default="pn-llm", help="seed of the bootstrap")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="freeze manifest: also analyze public, unpublished and synthetic families apart",
    )
    arguments = parser.parse_args()
    records = tuple(
        RunRecord.model_validate_json(line)
        for path in arguments.records
        for line in path.read_text().splitlines()
        if line.strip()
    )
    provenance = (
        ()
        if arguments.manifest is None
        else tuple(
            FamilyProvenance(family=f.family, provenance=f.provenance)
            for f in FreezeManifest.model_validate_json(arguments.manifest.read_text()).families
        )
    )
    analysis = analyze_runs(records=records, seed=arguments.seed, provenance=provenance)
    sys.stdout.write(analysis.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    analyze_main()
