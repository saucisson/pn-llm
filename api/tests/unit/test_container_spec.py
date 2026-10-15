from pathlib import Path

from app.domain.models import Limits
from app.infrastructure.docker_runner import NAME_PREFIX, build_spec


def spec():
    return build_spec(
        image="engine:1", job_id="abc", work_dir=Path("/srv/job"), limits=Limits(memory_mb=512)
    )


def test_the_container_has_no_network_a_read_only_root_and_no_capabilities():
    built = spec()
    assert built.network_mode == "none"
    assert built.read_only is True
    assert built.cap_drop == ("ALL",)
    assert built.security_opt == ("no-new-privileges",)


def test_memory_cpu_and_processes_are_bounded():
    built = spec()
    assert built.memory_mb == 512
    assert built.cpus == 1.0
    assert built.pids_limit == 256


def test_the_container_is_named_after_its_job_and_runs_the_image_entrypoint():
    built = spec()
    assert built.name == f"{NAME_PREFIX}abc"
    assert built.job_id == "abc"
    assert built.command is None
    assert built.image == "engine:1"


def test_input_and_output_directories_come_from_the_work_directory():
    built = spec()
    assert built.input_dir == "/srv/job/input"
    assert built.output_dir == "/srv/job/output"
