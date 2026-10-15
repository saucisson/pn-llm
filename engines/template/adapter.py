"""Adapter of REPLACE_NAME: translates formulas to the tool's syntax and its output back.

Copy to engines/<name>/adapter.py. The kit (pnverif_engine) reads the request, writes the result
envelope and the trace files, and turns a crash into a failed envelope. This file only knows
the tool. Rules: docs/engine-integration-checklist.md.
"""

import os

from pnverif_engine import AdapterAnswer, AdapterInput, normalize_verdict, run_adapter

TOOL_NAME = "REPLACE_NAME"
# The image build records the pinned version in this variable (see the Dockerfile).
TOOL_VERSION = os.environ["TOOL_VERSION"]


def check(given: AdapterInput) -> tuple[AdapterAnswer, ...]:  # noqa: PLR0917 - callback of run_adapter
    """Run the tool on ``given.net_path`` for each formula and report its answers.

    For each formula: render it in the tool's syntax (``rendered``, kept for audit), run the tool
    within ``given.request.limits``, map the output with ``normalize_verdict`` (anything unclear
    is UNKNOWN, never FALSE), and list the transitions of a counterexample in ``trace``.
    """
    return tuple(
        AdapterAnswer(
            formula_id=formula.id,
            verdict=normalize_verdict(raw=None),
            warnings=("template_adapter_does_nothing",),
        )
        for formula in given.request.formulas
    )


if __name__ == "__main__":
    run_adapter(tool_name=TOOL_NAME, tool_version=TOOL_VERSION, check=check)
