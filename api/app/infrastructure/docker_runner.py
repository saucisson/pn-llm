"""Runs engine containers through the Docker SDK.

The only module that talks to the Docker daemon. Every container is ephemeral, named after its
job, labelled, isolated (no network, read-only root, no capabilities, bounded memory, CPU and
processes) and always removed, whether it finishes, times out or is cancelled (ADR 0004,
docs/security-container-launching.md). Arguments come from internal values only, never from
request text.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from app.domain.models import DomainModel, Limits

CPUS = 1.0
PIDS_LIMIT = 256
TMP_SIZE_MB = 256
LOG_TAIL_BYTES = 8192
NAME_PREFIX = "pnverif-"
JOB_LABEL = "pnverif.job"
INPUT_MOUNT = "/work/input"
OUTPUT_MOUNT = "/work/output"
NANO_CPUS_PER_CPU = 1_000_000_000
SIGKILL_EXIT = 137


class DockerTimeoutError(Exception):
    """The container did not finish within its time budget; it was killed and removed."""


class DockerUnavailableError(Exception):
    """The Docker daemon cannot be reached."""


class ContainerSpec(DomainModel):
    """Everything that defines how an engine container is created: the security profile."""

    image: str
    name: str
    job_id: str
    input_dir: str
    output_dir: str
    memory_mb: int
    cpus: float = CPUS
    pids_limit: int = PIDS_LIMIT
    network_mode: str = "none"
    read_only: bool = True
    cap_drop: tuple[str, ...] = ("ALL",)
    security_opt: tuple[str, ...] = ("no-new-privileges",)
    command: tuple[str, ...] | None = None  # None: the image's own entrypoint (production)


class RunOutcome(DomainModel):
    """How a container ended."""

    exit_code: int
    oom_killed: bool
    log_tail: str


def build_spec(*, image: str, job_id: str, work_dir: Path, limits: Limits) -> ContainerSpec:
    """Return the container definition for one engine run of a job."""
    return ContainerSpec(
        image=image,
        name=f"{NAME_PREFIX}{job_id}",
        job_id=job_id,
        input_dir=str(work_dir / "input"),
        output_dir=str(work_dir / "output"),
        memory_mb=limits.memory_mb,
    )


class DockerRunner:
    """Inspect images and run engine containers."""

    def client(self) -> docker.DockerClient:
        """Return a client of the local daemon.

        Raises:
            DockerUnavailableError: if the daemon cannot be reached.
        """
        try:
            client = docker.from_env()
            client.ping()
        except DockerException as exc:
            raise DockerUnavailableError(str(exc)) from exc
        return client

    def image_present(self, *, image: str) -> bool:
        """Return True if ``image`` exists locally (False if Docker is unreachable)."""
        try:
            self.client().images.get(image)
        except DockerUnavailableError, ImageNotFound:
            return False
        except DockerException:
            return False
        return True

    def run(self, *, image: str, job_id: str, work_dir: Path, limits: Limits) -> RunOutcome:
        """Run ``image`` for a job: ``work_dir/input`` read-only, ``work_dir/output`` writable.

        Raises:
            DockerTimeoutError: if the run exceeds ``limits.timeout_s``.
            DockerUnavailableError: if the daemon cannot be reached.
        """
        spec = build_spec(image=image, job_id=job_id, work_dir=work_dir, limits=limits)
        return self.run_spec(spec=spec, timeout_s=limits.timeout_s)

    def run_spec(self, *, spec: ContainerSpec, timeout_s: int) -> RunOutcome:
        """Create, start and wait for a container, then remove it, whatever happened.

        Raises:
            DockerTimeoutError: if the container is still running after ``timeout_s`` seconds.
            DockerUnavailableError: if the daemon cannot be reached.
        """
        client = self.client()
        # A container left by a crashed process would block the name.
        self.remove_leftovers(job_id=spec.job_id)
        try:
            container = client.containers.create(
                spec.image,
                command=None if spec.command is None else list(spec.command),
                name=spec.name,
                labels={JOB_LABEL: spec.job_id},
                network_mode=spec.network_mode,
                read_only=spec.read_only,
                mem_limit=f"{spec.memory_mb}m",
                memswap_limit=f"{spec.memory_mb}m",  # no swap: the memory limit is the limit
                nano_cpus=int(spec.cpus * NANO_CPUS_PER_CPU),
                pids_limit=spec.pids_limit,
                cap_drop=list(spec.cap_drop),
                security_opt=list(spec.security_opt),
                tmpfs={"/tmp": f"rw,noexec,nosuid,size={TMP_SIZE_MB}m"},  # noqa: S108 - container-private tmpfs
                volumes={
                    spec.input_dir: {"bind": INPUT_MOUNT, "mode": "ro"},
                    spec.output_dir: {"bind": OUTPUT_MOUNT, "mode": "rw"},
                },
            )
        except DockerException as exc:
            raise DockerUnavailableError(str(exc)) from exc
        try:
            container.start()
            try:
                status = container.wait(timeout=timeout_s)
            except (ReadTimeout, RequestsConnectionError) as exc:
                container.kill()
                raise DockerTimeoutError(spec.image) from exc
            container.reload()
            exit_code = int(status["StatusCode"])
            # Docker does not always set OOMKilled when the kernel kills the process (it depends on
            # the cgroup version and on which process dies), so a SIGKILL exit counts too. A kill
            # we ordered ourselves (timeout, cancellation) never reaches this point as a result.
            oom_killed = (
                bool(container.attrs["State"].get("OOMKilled", False)) or exit_code == SIGKILL_EXIT
            )
            logs = container.logs(tail=100)[-LOG_TAIL_BYTES:].decode("utf-8", errors="replace")
            return RunOutcome(exit_code=exit_code, oom_killed=oom_killed, log_tail=logs)
        finally:
            with contextlib.suppress(NotFound):  # already removed by a concurrent stop()
                container.remove(force=True)

    def stop(self, *, job_id: str) -> None:
        """Kill the containers of a job, if any: cancellation. The run that owns them cleans up."""
        for leftover in self.containers_of(job_id=job_id):
            with contextlib.suppress(DockerException):  # already stopped or gone: nothing to do
                leftover.kill()

    def remove_leftovers(self, *, job_id: str) -> None:
        """Remove the containers of a job, running or not: clean-up before a new run."""
        for leftover in self.containers_of(job_id=job_id):
            with contextlib.suppress(NotFound):
                leftover.remove(force=True)

    def containers_of(self, *, job_id: str) -> list[Any]:
        """Return the containers of a job and of its portfolio (``<job>.<engine>``).

        None are returned if the daemon is unreachable.
        """
        try:
            client = self.client()
            labelled = client.containers.list(all=True, filters={"label": f"{JOB_LABEL}={job_id}"})
            pattern = f"^/{NAME_PREFIX}{re.escape(job_id)}\\.[A-Za-z0-9_-]+$"
            portfolio = client.containers.list(all=True, filters={"name": pattern})
            return list({c.id: c for c in (*labelled, *portfolio)}.values())
        except DockerUnavailableError:
            return []  # nothing can be running if the daemon is gone
