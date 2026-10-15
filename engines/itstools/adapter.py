"""Adapter of ITS-Tools: formulas to the contest's property files, its output back to verdicts.

ITS-Tools reads the contest's formats (a folder with ``model.pnml`` and ``<Examination>.xml``) and
prints one ``FORMULA <id> <answer>`` line per formula it solved. The examination names the family
of the formulas, so the formulas of a request are grouped by it and each group is one run.
It gives no counterexample in this mode, so no trace is returned.
Rules: docs/engine-integration-checklist.md.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from pnverif_engine import AdapterAnswer, AdapterInput, run_adapter

from app.domain.formula import Enabled, Formula, subexpressions
from app.domain.mcc_xml import render_property_set
from app.domain.models import Verdict
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml

TOOL_NAME = "itstools"
TOOL_VERSION = os.environ["TOOL_VERSION"]
LAUNCHER = "/opt/tool/its-tools"
# Lets the tool's chmod of its own binaries succeed on the read-only root (see keepmode.c).
SHIM = "/opt/shim/keepmode.so"
# Left to the container for starting and stopping, out of the budget given to the tool.
OVERHEAD_S = 3
# The tool is asked to stop by itself this long before it is killed.
GRACE_S = 5
SIGKILL = -9
# The JVM keeps this share of the memory limit; the rest is for the native solvers it starts.
HEAP_SHARE = 0.6
# The options the contest wrapper uses (BenchKit_head.sh): the symbolic engines and the SMT
# solver. Without them the tool only tries its light techniques and leaves most CTL and LTL
# formulas unsolved.
CONTEST_OPTIONS = ("-its", "-order", "META", "-manyOrder", "-smt")
# The ones of its-tools.ini: giving any -vmargs replaces them all, so they are repeated here.
JVM_OPTIONS = (
    "-Dosgi.locking=none",
    "-Declipse.stateSaveDelayInterval=-1",
    "-Xss128m",
    "-Xms40m",
    "-Djdk.lang.Process.launchMechanism=vfork",
)
FAMILY = {"state": "Reachability", "ctl": "CTL", "ltl": "LTL"}
ANSWER = re.compile(r"^FORMULA (\S+) (TRUE|FALSE|CANNOT_COMPUTE)\b", re.MULTILINE)
ANSWERS = {"TRUE": Verdict.TRUE, "FALSE": Verdict.FALSE, "CANNOT_COMPUTE": Verdict.UNKNOWN}


def examination_of(*, formula: Formula) -> str:
    """Return the examination a formula belongs to: its family, then what its atoms count."""
    fireability = any(
        isinstance(located.expression, Enabled)
        for located in subexpressions(expression=formula.ast, path="")
    )
    return FAMILY[formula.logic] + ("Fireability" if fireability else "Cardinality")


def check(given: AdapterInput) -> tuple[AdapterAnswer, ...]:  # noqa: PLR0917 - callback of run_adapter
    """Run ITS-Tools once per examination, within an equal share of the remaining time."""
    deadline = time.monotonic() + max(given.request.limits.timeout_s - OVERHEAD_S, 1)
    groups: dict[str, list[Formula]] = {}
    for formula in given.request.formulas:
        groups.setdefault(examination_of(formula=formula), []).append(formula)
    heap_mb = int(given.request.limits.memory_mb * HEAP_SHARE)
    answers: dict[str, AdapterAnswer] = {}
    for position, (examination, formulas) in enumerate(sorted(groups.items())):
        budget = max((deadline - time.monotonic()) / (len(groups) - position), GRACE_S + 1)
        started = time.monotonic()
        # The ids written for the tool are plain, whatever the ids of the request are.
        renamed = tuple(
            formula.model_copy(update={"id": f"q{index}"}) for index, formula in enumerate(formulas)
        )
        rendered = render_property_set(formulas=renamed)
        if "<deadlock/>" in rendered:
            # ITS-Tools fails on the deadlock atom, and a failure loses the whole group. A deadlock
            # is a marking where no transition is fireable: the same meaning, in atoms it reads.
            document = import_pnml(payload=given.net_path.read_bytes(), limits=DocumentLimits())
            transitions = "".join(
                f"<transition>{escape(transition.id)}</transition>"
                for located in document.located_containers()
                for transition in located.container.transitions
            )
            rendered = rendered.replace(
                "<deadlock/>",
                f"<negation><is-fireable>{transitions}</is-fireable></negation>"
                if transitions
                else "<true/>",
            )
        warnings: list[str] = []
        verdicts: dict[str, Verdict] = {}
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch) / "input"
            folder.mkdir()
            shutil.copy(given.net_path, folder / "model.pnml")
            (folder / f"{examination}.xml").write_text(rendered)
            try:
                run = subprocess.run(  # noqa: S603 - fixed executable, arguments built here
                    [
                        LAUNCHER,
                        "-configuration",
                        f"{scratch}/configuration",
                        "-data",
                        f"{scratch}/workspace",
                        "-pnfolder",
                        str(folder),
                        "-examination",
                        examination,
                        *CONTEST_OPTIONS,
                        "-timeout",
                        str(max(int(budget - GRACE_S), 1)),
                        "-vmargs",
                        *JVM_OPTIONS,
                        f"-Xmx{heap_mb}m",
                    ],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=budget,
                    check=False,
                    cwd=scratch,
                    env={**os.environ, "HOME": scratch, "LD_PRELOAD": SHIM},
                )
                verdicts = {name: ANSWERS[word] for name, word in ANSWER.findall(run.stdout)}
                if run.returncode == SIGKILL:
                    verdicts = {}
                    warnings.append("its_tools_killed_by_sigkill")
                elif not verdicts:
                    warnings.append(f"its_tools_gave_no_answer_exit_{run.returncode}")
            except subprocess.TimeoutExpired as expired:
                # What the tool solved before the kill is still an answer.
                partial = expired.stdout or b""
                text = partial if isinstance(partial, str) else partial.decode(errors="replace")
                verdicts = {name: ANSWERS[word] for name, word in ANSWER.findall(text)}
                run = None
        spent = time.monotonic() - started
        for index, formula in enumerate(formulas):
            if run is None:
                verdict = verdicts.get(f"q{index}", Verdict.TIMEOUT)
            elif run.returncode == SIGKILL:
                verdict = Verdict.OOM
            else:
                verdict = verdicts.get(f"q{index}", Verdict.UNKNOWN)
            answers[formula.id] = AdapterAnswer(
                formula_id=formula.id,
                verdict=verdict,
                rendered=rendered,
                time_s=spent,
                warnings=(*warnings, "no_counterexample_from_its_tools"),
            )
    return tuple(answers[formula.id] for formula in given.request.formulas)


if __name__ == "__main__":
    run_adapter(tool_name=TOOL_NAME, tool_version=TOOL_VERSION, check=check)
