"""Thin wrapper around the ``docker`` command line.

Everything that starts a subprocess lives here. Arguments are built from internal values only
(never from request text) and no shell is used.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.domain.models import Limits

IMAGE_CHECK_TIMEOUT_S = 10
KILL_GRACE_S = 10
CPUS = "1"
PIDS_LIMIT = "256"


class DockerTimeoutError(Exception):
    """The container did not finish within its time budget."""


class DockerRunner:
    """Inspect images and run engine containers."""

    def image_present(self, *, image: str) -> bool:
        """Return True if ``image`` exists locally (False if Docker is missing or unreachable)."""
        docker = shutil.which("docker")
        if docker is None:
            return False
        try:
            result = subprocess.run(  # noqa: S603  (fixed arguments, no shell)
                [docker, "image", "inspect", image],
                capture_output=True,
                timeout=IMAGE_CHECK_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def run(self, *, image: str, work_dir: Path, limits: Limits) -> None:
        """Run ``image`` with ``work_dir/input`` (read-only) and ``work_dir/output`` mounted.

        The container has no network, a read-only root filesystem and bounded memory, CPU and
        processes.

        Raises:
            DockerTimeoutError: if the run exceeds the time limit (plus a short grace period).
            FileNotFoundError: if the docker executable is not installed.
        """
        docker = shutil.which("docker")
        if docker is None:
            raise FileNotFoundError("docker executable not found")
        command = [
            docker, "run", "--rm",
            "--network", "none",
            "--read-only",
            "--memory", f"{limits.memory_mb}m",
            "--cpus", CPUS,
            "--pids-limit", PIDS_LIMIT,
            "-v", f"{work_dir}/input:/work/input:ro",
            "-v", f"{work_dir}/output:/work/output",
            image,
        ]  # fmt: skip
        try:
            subprocess.run(  # noqa: S603  (fixed arguments, no shell)
                command,
                capture_output=True,
                timeout=limits.timeout_s + KILL_GRACE_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # The container may outlive the killed client; see the "robust Docker runner" issue.
            raise DockerTimeoutError(image) from exc
