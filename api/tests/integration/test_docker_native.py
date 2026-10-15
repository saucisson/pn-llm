"""The native engine image, for real. Skipped unless Docker and the image are available.

Build the image first:  docker build -f engines/native/Dockerfile -t pn-llm-verif/native:1.0 .
"""

import pytest

from app.domain.analyses import find_operation
from app.domain.engine_contract import EngineRequest
from app.domain.models import Limits
from app.domain.net_structure import build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.operations import compute_on
from app.domain.pnml_import import import_pnml
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from tests.support import MUTEX_PNML

pytestmark = pytest.mark.docker

registry = EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())


@pytest.fixture(autouse=True)
def _require_image():
    if not DockerRunner().image_present(image=DEFAULT_ENGINES["native"].image or ""):
        pytest.skip("the native engine image is not built here")


@pytest.mark.parametrize("operation", sorted(DEFAULT_ENGINES["native"].operations))
def test_the_container_gives_the_same_answer_as_the_function(operation):
    request = EngineRequest(
        kind="analysis",
        net_id="n1",
        operation=operation,
        parameters={},
        limits=Limits(memory_mb=512, timeout_s=60),
    )
    report = registry.run_operation(
        engine="native", pnml=MUTEX_PNML, request=request, job_id=f"it-native-{operation}"
    )
    assert report.status == "ok"
    assert (report.tool_name, report.tool_version) == ("native", DEFAULT_ENGINES["native"].version)
    structure = build_structure(
        document=import_pnml(payload=MUTEX_PNML, limits=DocumentLimits()), net_id="n1"
    )
    expected = compute_on(
        definition=find_operation(name=operation), structure=structure, parameters={}
    )
    assert report.result == expected.model_dump(mode="json")


def test_an_unknown_operation_is_a_failure_with_a_reason_not_a_result():
    request = EngineRequest(
        kind="analysis", net_id="n1", operation="nope", limits=Limits(memory_mb=512, timeout_s=60)
    )
    report = registry.run_operation(
        engine="native", pnml=MUTEX_PNML, request=request, job_id="it-native-unknown"
    )
    assert (report.status, report.error_code) == ("failed", "adapter_exception")
    assert report.result is None
