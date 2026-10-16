"""Write the evaluation report (``python -m app.report_evaluation``).

Reads the analysis (``app.analyze_runs``), optionally the soundness audit (``app.audit_sessions``),
the deviations (one per line) and the negative results file, and prints the report as Markdown.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.domain.analysis_stats import EvaluationAnalysis
from app.domain.evaluation_report import render_report
from app.domain.soundness import SoundnessReport


def report_main() -> None:
    """Read the inputs and print the report."""
    parser = argparse.ArgumentParser(description="Write the evaluation report.")
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--soundness", type=Path, help="output of app.audit_sessions")
    parser.add_argument("--deviations", type=Path, help="one deviation per line")
    parser.add_argument("--negative", type=Path, default=Path("bench/results/NEGATIVE.md"))
    arguments = parser.parse_args()
    sys.stdout.write(
        render_report(
            analysis=EvaluationAnalysis.model_validate_json(arguments.analysis.read_text()),
            soundness=None
            if arguments.soundness is None
            else SoundnessReport.model_validate_json(arguments.soundness.read_text()),
            deviations=()
            if arguments.deviations is None
            else tuple(
                line.strip()
                for line in arguments.deviations.read_text().splitlines()
                if line.strip()
            ),
            negative_results=arguments.negative.read_text() if arguments.negative.exists() else "",
        )
    )


if __name__ == "__main__":
    report_main()
