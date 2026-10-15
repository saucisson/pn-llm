"""Runs the dummy engine image for real. Skipped unless Docker and the image are available.

Build the image first:  docker compose --profile engines build
"""

import json

import pytest

from app.domain.models import Limits
from app.infrastructure.docker_runner import DockerRunner
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
    (tmp_path / "input" / "request.json").write_text(make_request().model_dump_json())

    outcome = runner.run(
        image=IMAGE,
        job_id="it-dummy",
        work_dir=tmp_path,
        limits=Limits(memory_mb=256, timeout_s=60),
    )
    assert outcome.exit_code == 0

    results = json.loads((tmp_path / "output" / "result.json").read_text())["results"]
    assert [r["id"] for r in results] == ["f1"]
    assert results[0]["verdict"] == "UNKNOWN"  # never TRUE/FALSE without verification
