"""Run real containers: isolation, limits, timeouts, OOM and cancellation (ADR 0004).

Needs a Docker daemon; the small public image alpine is pulled if missing. Skipped otherwise.
"""

import threading
import time
from pathlib import Path

import docker as docker_sdk
import pytest

from app.infrastructure.docker_runner import (
    JOB_LABEL,
    ContainerSpec,
    DockerRunner,
    DockerTimeoutError,
)

pytestmark = pytest.mark.docker

IMAGE = "alpine:3.20"
OUTPUT_DIR_MODE = 0o777

runner = DockerRunner()


@pytest.fixture(scope="module", autouse=True)
def _alpine():
    try:
        client = runner.client()
        try:
            client.images.get(IMAGE)
        except docker_sdk.errors.ImageNotFound:
            client.images.pull(IMAGE)
    except Exception as exc:  # noqa: BLE001 - any failure here means no usable Docker for the tests
        pytest.skip(f"Docker with {IMAGE} is not available: {exc}")


@pytest.fixture
def dirs(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "output").chmod(OUTPUT_DIR_MODE)
    return tmp_path


def spec_for(*, dirs: Path, job_id: str, script: str, memory_mb: int = 64, **overrides):
    return ContainerSpec(
        image=IMAGE,
        name=f"pnverif-{job_id}",
        job_id=job_id,
        input_dir=str(dirs / "input"),
        output_dir=str(dirs / "output"),
        memory_mb=memory_mb,
        command=("sh", "-c", script),
        **overrides,
    )


def leftovers(*, job_id: str):
    return runner.client().containers.list(all=True, filters={"label": f"{JOB_LABEL}={job_id}"})


def test_the_container_has_no_network_interface_but_loopback(dirs):
    outcome = runner.run_spec(
        spec=spec_for(dirs=dirs, job_id="it-net", script="ls /sys/class/net"), timeout_s=60
    )
    assert outcome.log_tail.split() == ["lo"]
    assert outcome.exit_code == 0


def test_the_root_filesystem_is_read_only_but_output_and_tmp_are_writable(dirs):
    script = "touch /x; echo root=$?; touch /work/output/y; echo out=$?; touch /tmp/z; echo tmp=$?"
    outcome = runner.run_spec(spec=spec_for(dirs=dirs, job_id="it-ro", script=script), timeout_s=60)
    assert "root=1" in outcome.log_tail
    assert "out=0" in outcome.log_tail
    assert "tmp=0" in outcome.log_tail
    assert (dirs / "output" / "y").exists()


def test_input_is_mounted_read_only(dirs):
    (dirs / "input" / "net.pnml").write_text("<pnml/>")
    script = "cat /work/input/net.pnml; rm /work/input/net.pnml; echo rm=$?"
    outcome = runner.run_spec(spec=spec_for(dirs=dirs, job_id="it-in", script=script), timeout_s=60)
    assert "<pnml/>" in outcome.log_tail
    assert "rm=1" in outcome.log_tail
    assert (dirs / "input" / "net.pnml").exists()


def test_all_capabilities_are_dropped(dirs):
    outcome = runner.run_spec(
        spec=spec_for(dirs=dirs, job_id="it-cap", script="grep CapEff /proc/self/status"),
        timeout_s=60,
    )
    assert outcome.log_tail.split()[-1] == "0000000000000000"


def test_the_number_of_processes_is_bounded(dirs):
    script = "i=0; while [ $i -lt 40 ]; do sleep 20 & i=$((i+1)); done; wait"
    outcome = runner.run_spec(
        spec=spec_for(dirs=dirs, job_id="it-pids", script=script, pids_limit=10), timeout_s=60
    )
    assert "ork" in outcome.log_tail  # "can't fork": the 11th process is refused


def test_a_timeout_kills_and_removes_the_container(dirs):
    started = time.monotonic()
    with pytest.raises(DockerTimeoutError):
        runner.run_spec(spec=spec_for(dirs=dirs, job_id="it-time", script="sleep 60"), timeout_s=2)
    assert time.monotonic() - started < 30
    assert leftovers(job_id="it-time") == []


def test_exceeding_memory_is_reported_as_an_oom_kill(dirs):
    script = "a=xxxxxxxxxxxxxxxx; while true; do a=$a$a; done"
    outcome = runner.run_spec(
        spec=spec_for(dirs=dirs, job_id="it-oom", script=script, memory_mb=32), timeout_s=60
    )
    assert outcome.oom_killed is True
    assert outcome.exit_code == 137
    assert leftovers(job_id="it-oom") == []


def test_stopping_a_job_kills_its_container_and_run_returns(dirs):
    result = {}

    def run():
        result["outcome"] = runner.run_spec(
            spec=spec_for(dirs=dirs, job_id="it-stop", script="sleep 60"), timeout_s=120
        )

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 30
    while not leftovers(job_id="it-stop") and time.monotonic() < deadline:
        time.sleep(0.2)
    runner.stop(job_id="it-stop")
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert result["outcome"].exit_code == 137
    assert leftovers(job_id="it-stop") == []


def test_a_container_left_by_a_crashed_process_does_not_block_the_name(dirs):
    client = runner.client()
    client.containers.create(IMAGE, name="pnverif-it-left", labels={JOB_LABEL: "it-left"})
    outcome = runner.run_spec(
        spec=spec_for(dirs=dirs, job_id="it-left", script="echo ok"), timeout_s=60
    )
    assert outcome.exit_code == 0


def test_stopping_an_unknown_job_is_a_no_op():
    runner.stop(job_id="it-nothing-here")


def test_image_presence():
    assert runner.image_present(image=IMAGE) is True
    assert runner.image_present(image="pn-llm-verif/does-not-exist:0") is False
