import subprocess

import pytest

from app.domain.models import Limits
from app.infrastructure import docker_runner
from app.infrastructure.docker_runner import DockerRunner, DockerTimeoutError

runner = DockerRunner()


def completed(*, returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode)


@pytest.fixture
def docker_installed(monkeypatch):
    monkeypatch.setattr(docker_runner.shutil, "which", lambda _: "/usr/bin/docker")


def test_image_absent_when_docker_is_not_installed(monkeypatch):
    monkeypatch.setattr(docker_runner.shutil, "which", lambda _: None)
    assert runner.image_present(image="img") is False


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (1, False)])
def test_image_presence_follows_the_exit_code(monkeypatch, docker_installed, returncode, expected):
    monkeypatch.setattr(
        docker_runner.subprocess, "run", lambda *a, **k: completed(returncode=returncode)
    )
    assert runner.image_present(image="img") is expected


@pytest.mark.parametrize("error", [OSError("boom"), subprocess.TimeoutExpired("docker", 1)])
def test_image_absent_when_docker_cannot_be_reached(monkeypatch, docker_installed, error):
    def raiser(*args, **kwargs):
        raise error

    monkeypatch.setattr(docker_runner.subprocess, "run", raiser)
    assert runner.image_present(image="img") is False


def test_container_is_isolated_and_limited(monkeypatch, docker_installed, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"], seen["kwargs"] = command, kwargs
        return completed()

    monkeypatch.setattr(docker_runner.subprocess, "run", fake_run)
    runner.run(image="engine:1", work_dir=tmp_path, limits=Limits(memory_mb=512, timeout_s=30))

    command = seen["command"]
    assert command[:3] == ["/usr/bin/docker", "run", "--rm"]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--memory") + 1] == "512m"
    assert f"{tmp_path}/input:/work/input:ro" in command  # inputs are mounted read-only
    assert command[-1] == "engine:1"
    assert seen["kwargs"]["timeout"] == 30 + docker_runner.KILL_GRACE_S
    assert "shell" not in seen["kwargs"]  # never through a shell


def test_timeout_is_reported_as_a_dedicated_error(monkeypatch, docker_installed, tmp_path):
    def raiser(*args, **kwargs):
        raise subprocess.TimeoutExpired("docker", 1)

    monkeypatch.setattr(docker_runner.subprocess, "run", raiser)
    with pytest.raises(DockerTimeoutError):
        runner.run(image="engine:1", work_dir=tmp_path, limits=Limits())


def test_missing_docker_raises_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_runner.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        runner.run(image="engine:1", work_dir=tmp_path, limits=Limits())
