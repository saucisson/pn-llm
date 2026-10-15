"""Known-verdict tests of the Tapaal image. Skipped unless Docker and the image are available.

Build the image first:  docker build -f engines/tapaal/Dockerfile -t pn-llm-verif/tapaal:4.4.2 .
"""

import pytest

from app.domain.engine_contract import EngineRequest
from app.domain.formula_text import formula_from_text
from app.domain.models import Limits, Verdict
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import read_report
from tests.support import MUTEX_PNML

IMAGE = "pn-llm-verif/tapaal:4.4.2"
OUTPUT_DIR_MODE = 0o777

pytestmark = pytest.mark.docker

runner = DockerRunner()

# (id, text, logic, expected verdict) on the mutex net: two processes share one lock, so the
# critical section holds at most one token.
CASES = (
    ("reach_true", '"crit1" >= 1', "state", Verdict.TRUE),
    ("reach_false", '"crit1" >= 3', "state", Verdict.FALSE),
    ("ctl_true", 'AG "crit1" <= 1', "ctl", Verdict.TRUE),
    ("ctl_false", 'AG "crit1" < 1', "ctl", Verdict.FALSE),
    ("ltl_true", 'G "crit1" <= 1', "ltl", Verdict.TRUE),
    ("ltl_false", 'G "crit1" < 1', "ltl", Verdict.FALSE),
    ("deadlock_false", "deadlock", "state", Verdict.FALSE),
)


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    if not runner.image_present(image=IMAGE):
        pytest.skip(f"{IMAGE} is not available (needs Docker and a built image)")
    work = tmp_path_factory.mktemp("tapaal")
    (work / "input").mkdir()
    (work / "output").mkdir()
    (work / "output").chmod(OUTPUT_DIR_MODE)
    (work / "input" / "net.pnml").write_bytes(MUTEX_PNML)
    formulas = tuple(
        formula_from_text(text=text, formula_id=name, logic=logic, gloss="", origin="user")
        for name, text, logic, _ in CASES
    )
    request = EngineRequest(
        net_id="n1", formulas=formulas, limits=Limits(memory_mb=1024, timeout_s=120)
    )
    (work / "input" / "request.json").write_text(request.model_dump_json())
    outcome = runner.run(image=IMAGE, job_id="it-tapaal", work_dir=work, limits=request.limits)
    assert outcome.exit_code == 0
    return read_report(output_dir=work / "output")


def test_verdicts_are_the_known_ones_with_the_pinned_version(report):
    assert report.status == "ok"
    assert report.tool_version == "4.4.2"
    got = {item.result.id: item.result.verdict for item in report.results}
    assert got == {name: verdict for name, _, _, verdict in CASES}


def test_the_formula_is_kept_in_the_tools_own_syntax(report):
    rendered = {item.result.id: item.result.rendered for item in report.results}
    assert "<exists-path><finally>" in rendered["reach_true"]


def test_a_violated_invariant_comes_with_a_counterexample(report):
    by_id = {item.result.id: item for item in report.results}
    trace = by_id["ctl_false"].trace
    assert trace is not None
    assert [step.transition for step in trace.steps] == ["enter1"]
