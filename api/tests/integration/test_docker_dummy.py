"""Runs the dummy engine image for real. Skipped unless Docker and the image are available.

Build the image first:  docker compose --profile engines build
"""

import json

import pytest

from app.domain.models import Limits
from app.infrastructure.docker_runner import DockerRunner

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
    (tmp_path / "input" / "request.json").write_text(
        json.dumps({"formulas": [{"id": "f1", "text": "x"}], "engine": "dummy"})
    )

    runner.run(image=IMAGE, work_dir=tmp_path, limits=Limits(memory_mb=256, timeout_s=60))

    results = json.loads((tmp_path / "output" / "result.json").read_text())["results"]
    assert [r["id"] for r in results] == ["f1"]
    assert results[0]["verdict"] == "UNKNOWN"  # never TRUE/FALSE without verification
