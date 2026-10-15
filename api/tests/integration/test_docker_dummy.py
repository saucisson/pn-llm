"""Runs the dummy engine image for real. Skipped unless Docker and the image are available.

Build the image first:  docker compose --profile engines build
"""

import pytest

from app.domain.engine_contract import EngineRequest
from app.domain.models import Limits, Verdict
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import read_report
from tests.support import make_request

IMAGE = "pn-llm-verif/dummy:latest"
OUTPUT_DIR_MODE = 0o777

pytestmark = pytest.mark.docker

runner = DockerRunner()


@pytest.fixture(autouse=True)
def _require_image():
    if not runner.image_present(image=IMAGE):
        pytest.skip(f"{IMAGE} is not available (needs Docker and a built image)")


def test_dummy_container_honours_the_engine_contract(tmp_path, mutex_pnml):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "output").chmod(OUTPUT_DIR_MODE)
    (tmp_path / "input" / "net.pnml").write_bytes(mutex_pnml)
    check = make_request()
    request = EngineRequest(net_id="n1", formulas=check.formulas, limits=check.limits)
    (tmp_path / "input" / "request.json").write_text(request.model_dump_json())

    outcome = runner.run(
        image=IMAGE,
        job_id="it-dummy",
        work_dir=tmp_path,
        limits=Limits(memory_mb=256, timeout_s=60),
    )

    assert outcome.exit_code == 0
    report = read_report(output_dir=tmp_path / "output")
    assert report.status == "ok"
    assert report.tool_version == "0.2"
    assert [item.result.id for item in report.results] == ["f1"]
    assert report.results[0].result.verdict == Verdict.UNKNOWN  # never TRUE/FALSE unverified
