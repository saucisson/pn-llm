"""Adapter of SMPT: reachability formulas to the contest's property XML, its lines back to verdicts.

SMPT answers the contest's two reachability categories, so the formula trees are written with the
platform's own writer (``app.domain.mcc_xml``). It reads the PNML only when the file declares the
PNML namespace, so a copy with the namespace is given to it. The contest simplifies formulas in its
``--mcc`` mode, which does not know the ``deadlock`` atom: formulas that use it run apart, without
that mode. Formulas run in groups of the same kind, each group within an equal share of the time.
Rules: docs/engine-integration-checklist.md.
"""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from pnverif_engine import AdapterAnswer, AdapterInput, run_adapter

from app.domain.capabilities import asks_reachability
from app.domain.formula import Deadlock, Enabled, Formula, subexpressions
from app.domain.mcc_xml import render_property_set
from app.domain.models import Verdict

TOOL_NAME = "smpt"
TOOL_VERSION = os.environ["TOOL_VERSION"]
SMPT_DIRECTORY = "/opt/SMPT"
TINA_BIN = "/opt/tina/bin"
PNML_NAMESPACE = "http://www.pnml.org/version-2009/grammar/pnml"
# Left to the container for starting and stopping, out of the budget given to the tool.
OVERHEAD_S = 3
# SMPT stops itself a little before we would have to kill it, so that it can print what it has.
GRACE_S = 2
SIGKILL = -9
# Without the contest's mode and reductions SMPT must be told which methods to run.
EXPLICIT_METHODS = ("STATE-EQUATION", "BMC", "K-INDUCTION", "PDR-REACH")
ANSWER = re.compile(r"^FORMULA (\S+) (TRUE|FALSE)\b", re.MULTILINE)


def with_namespace(*, pnml: bytes) -> bytes:
    """Declare the PNML namespace on the root element if the file does not: same net, same ids."""
    root = re.search(rb"<pnml[^>]*>", pnml)
    if root is None or b"xmlns" in root.group(0):
        return pnml
    declared = root.group(0).replace(b"<pnml", b'<pnml xmlns="' + PNML_NAMESPACE.encode() + b'"', 1)
    return pnml.replace(root.group(0), declared, 1)


def kind_of(*, formula: Formula) -> tuple[bool, bool]:
    """Say whether a formula uses the deadlock atom and whether it uses fireability atoms."""
    nodes = [located.expression for located in subexpressions(expression=formula.ast, path="")]
    return (
        any(isinstance(node, Deadlock) for node in nodes),
        any(isinstance(node, Enabled) for node in nodes),
    )


def read_answers(*, stdout: str) -> dict[str, Verdict]:
    """Read the verdicts SMPT printed, by the id the formula was given."""
    return {
        found.group(1): Verdict.TRUE if found.group(2) == "TRUE" else Verdict.FALSE
        for found in ANSWER.finditer(stdout)
    }


def check(given: AdapterInput) -> tuple[AdapterAnswer, ...]:  # noqa: PLR0917 - callback of run_adapter
    """Run SMPT once per group of alike formulas, within an equal share of the remaining time."""
    deadline = time.monotonic() + max(given.request.limits.timeout_s - OVERHEAD_S, 1)
    formulas = given.request.formulas
    answers: dict[int, AdapterAnswer] = {}
    groups: dict[tuple[bool, bool], list[int]] = {}
    for index, formula in enumerate(formulas):
        if not asks_reachability(formula=formula):
            answers[index] = AdapterAnswer(
                formula_id=formula.id,
                verdict=Verdict.UNKNOWN,
                warnings=(f"smpt_checks_reachability_not_{formula.logic}",),
            )
        else:
            groups.setdefault(kind_of(formula=formula), []).append(index)
    pnml = with_namespace(pnml=Path(given.net_path).read_bytes())
    if b"symmetricnet" in pnml[:4096]:
        # Read as a P/T net, a colored net has another meaning: no answer rather than a wrong one.
        return tuple(
            AdapterAnswer(
                formula_id=f.id, verdict=Verdict.UNKNOWN, warnings=("colored_nets_not_supported",)
            )
            for f in formulas
        )
    pending = len(groups)
    for (has_deadlock, has_fireability), members in sorted(groups.items()):
        budget = max((deadline - time.monotonic()) / pending, 1)
        pending -= 1
        # Plain ids for the tool, ours are free text.
        named = tuple(formulas[i].model_copy(update={"id": f"q{i}"}) for i in members)
        rendered = render_property_set(formulas=named)
        started = time.monotonic()
        timed_out = False
        # The contest's options: reductions, and the simplification of formulas of its --mcc mode
        # (which does not know the deadlock atom: those formulas run on the net as it is).
        contest_mode = given.request.reduce and not has_deadlock
        with tempfile.TemporaryDirectory() as scratch:
            net = Path(scratch) / "model.pnml"
            net.write_bytes(pnml)
            query = Path(scratch) / "query.xml"
            query.write_text(rendered)
            command = [
                "python3",
                "-m",
                "smpt",
                "-n",
                str(net),
                "--xml",
                str(query),
                "--methods",
                *(("DUMMY",) if contest_mode else EXPLICIT_METHODS),
                "--global-timeout",
                str(max(int(budget) - GRACE_S, 1)),
                "--show-techniques",
                *(("--auto-reduce", "--project", "--mcc") if contest_mode else ()),
                *(("--fireability",) if has_fireability else ()),
            ]
            try:
                run = subprocess.run(  # noqa: S603 - fixed executable, arguments built here
                    command,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=budget,
                    check=False,
                    cwd=SMPT_DIRECTORY,
                    env={
                        "PATH": f"{TINA_BIN}:/usr/local/bin:/usr/bin:/bin",
                        "HOME": scratch,
                        "TMPDIR": scratch,
                        "PYTHONWARNINGS": "ignore",
                    },
                )
                stdout, code = run.stdout, run.returncode
            except subprocess.TimeoutExpired as expired:
                timed_out = True
                stdout = (
                    expired.stdout.decode(errors="replace")
                    if isinstance(expired.stdout, bytes)
                    else (expired.stdout or "")
                )
                code = None
        elapsed = time.monotonic() - started
        verdicts = read_answers(stdout=stdout)
        for index in members:
            verdict = verdicts.get(f"q{index}")
            warnings: list[str] = []
            if verdict is None:
                if timed_out:
                    verdict = Verdict.TIMEOUT
                elif code == SIGKILL:
                    verdict = Verdict.OOM
                    warnings.append("smpt_killed_by_sigkill")
                else:
                    verdict = Verdict.UNKNOWN
                    warnings.append(f"smpt_gave_no_answer_exit_{code}")
            answers[index] = AdapterAnswer(
                formula_id=formulas[index].id,
                verdict=verdict,
                rendered=rendered,
                time_s=elapsed,
                warnings=tuple(warnings),
            )
    return tuple(answers[index] for index in range(len(formulas)))


if __name__ == "__main__":
    run_adapter(tool_name=TOOL_NAME, tool_version=TOOL_VERSION, check=check)
