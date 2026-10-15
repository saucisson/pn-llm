"""Adapter of Tapaal's verifypn: formulas to its query XML, its output back to verdicts.

The contest's property XML is verifypn's native query format, so the formula trees are written
with the platform's own writer (``app.domain.mcc_xml``). Each formula runs in its own process, so
each gets its own time budget and its own counterexample.
Rules: docs/engine-integration-checklist.md.
"""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from pnverif_engine import AdapterAnswer, AdapterInput, run_adapter

from app.domain.mcc_xml import render_property_set
from app.domain.models import Verdict

TOOL_NAME = "tapaal"
TOOL_VERSION = os.environ["TOOL_VERSION"]
VERIFYPN = "/opt/tool/verifypn"
# Left to the container for starting and stopping, out of the budget given to the tool.
OVERHEAD_S = 3
SIGKILL = -9
ALGORITHM_OPTIONS = {"ctl": ("-ctl", "czero"), "ltl": ("-ltl", "tarjan"), "state": ()}
TRANSITION = re.compile(r'<transition id="([^"]*)"|<loop/>')
SATISFIED = "Query is satisfied."
NOT_SATISFIED = "Query is NOT satisfied."


def read_verdict(*, stdout: str) -> Verdict:
    """Read the answer of verifypn; anything but its two clear sentences is UNKNOWN."""
    lines = {line.strip() for line in stdout.splitlines()}
    if SATISFIED in lines and NOT_SATISFIED not in lines:
        return Verdict.TRUE
    if NOT_SATISFIED in lines and SATISFIED not in lines:
        return Verdict.FALSE
    return Verdict.UNKNOWN


def read_trace(*, stderr: str) -> tuple[tuple[str, ...], int | None] | None:
    """Read the transitions of the trace verifypn printed, and where its loop starts."""
    start = stderr.find("<trace>")
    end = stderr.find("</trace>")
    if start < 0 or end < 0:
        return None
    fired: list[str] = []
    loop_start = None
    for found in TRANSITION.finditer(stderr[start:end]):
        if found.group(1) is None:
            loop_start = len(fired)
        else:
            fired.append(found.group(1))
    return tuple(fired), loop_start


def check(given: AdapterInput) -> tuple[AdapterAnswer, ...]:  # noqa: PLR0917 - callback of run_adapter
    """Run verifypn once per formula, within an equal share of the remaining time."""
    deadline = time.monotonic() + max(given.request.limits.timeout_s - OVERHEAD_S, 1)
    with Path(given.net_path).open("rb") as net:
        colored = b"symmetricnet" in net.read(4096)
    answers = []
    formulas = given.request.formulas
    for index, formula in enumerate(formulas):
        rendered = render_property_set(formulas=(formula,))
        budget = max((deadline - time.monotonic()) / (len(formulas) - index), 1)
        warnings: list[str] = []
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as scratch:
            query = Path(scratch) / "query.xml"
            query.write_text(rendered)
            try:
                run = subprocess.run(  # noqa: S603 - fixed executable, arguments built here
                    [
                        VERIFYPN,
                        "-x",
                        "1",
                        "-t",
                        *ALGORITHM_OPTIONS[formula.logic],
                        str(given.net_path),
                        str(query),
                    ],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=budget,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                answers.append(
                    AdapterAnswer(
                        formula_id=formula.id,
                        verdict=Verdict.TIMEOUT,
                        rendered=rendered,
                        time_s=time.monotonic() - started,
                    )
                )
                continue
        verdict = read_verdict(stdout=run.stdout)
        if run.returncode == SIGKILL:
            verdict = Verdict.OOM
            warnings.append("verifypn_killed_by_sigkill")
        elif verdict is Verdict.UNKNOWN:
            warnings.append(f"verifypn_gave_no_answer_exit_{run.returncode}")
        trace = read_trace(stderr=run.stderr) if verdict in {Verdict.TRUE, Verdict.FALSE} else None
        if trace is not None and colored:
            # verifypn unfolds a colored net: its transitions are not the ones of the net given.
            warnings.append("trace_not_given_for_colored_net")
            trace = None
        if trace is not None and verdict is Verdict.TRUE:
            warnings.append("trace_is_a_witness_of_the_formula_not_a_counterexample")
        answers.append(
            AdapterAnswer(
                formula_id=formula.id,
                verdict=verdict,
                rendered=rendered,
                time_s=time.monotonic() - started,
                trace=trace[0] if trace else None,
                loop_start=trace[1] if trace else None,
                warnings=tuple(warnings),
            )
        )
    return tuple(answers)


if __name__ == "__main__":
    run_adapter(tool_name=TOOL_NAME, tool_version=TOOL_VERSION, check=check)
