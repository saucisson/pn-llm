"""Known-verdict tests of the ITS-Tools image. Skipped unless Docker and the image are available.

Build the image first (tag: the version in the Dockerfile):
  docker build -f engines/itstools/Dockerfile -t pn-llm-verif/itstools:1.0.0.202609112134 .
"""

import pytest

from app.domain.engine_contract import EngineRequest
from app.domain.formula_text import formula_from_text
from app.domain.models import Limits, Verdict
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import read_report
from tests.support import MUTEX_PNML

IMAGE = "pn-llm-verif/itstools:1.0.0.202609112134"
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
    work = tmp_path_factory.mktemp("itstools")
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
    outcome = runner.run(image=IMAGE, job_id="it-itstools", work_dir=work, limits=request.limits)
    assert outcome.exit_code == 0
    return read_report(output_dir=work / "output")


def test_verdicts_are_the_known_ones_with_the_pinned_version(report):
    assert report.status == "ok"
    assert report.tool_version == "1.0.0.202609112134"
    got = {item.result.id: item.result.verdict for item in report.results}
    assert got == {name: verdict for name, _, _, verdict in CASES}


def test_the_formula_is_kept_in_the_tools_own_syntax(report):
    rendered = {item.result.id: item.result.rendered for item in report.results}
    assert "<exists-path><finally>" in rendered["reach_true"]


def test_no_counterexample_is_invented_and_the_gap_is_said(report):
    for item in report.results:
        assert item.trace is None
        assert "no_counterexample_from_its_tools" in item.result.warnings
