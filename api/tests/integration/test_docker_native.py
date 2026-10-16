"""The native engine image, for real. Skipped unless Docker and the image are available.

Build the image first:  docker build -f engines/native/Dockerfile -t pn-llm-verif/native:1.8 .
"""

from pathlib import Path

import pytest

from app.domain.engine_contract import EngineRequest
from app.domain.models import Limits
from app.domain.net_validation import DocumentLimits
from app.domain.perform import perform
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


GUARDED = (Path(__file__).resolve().parents[1] / "corpus" / "colored" / "guarded.pnml").read_bytes()


@pytest.mark.parametrize("operation", sorted(DEFAULT_ENGINES["native"].operations))
def test_the_container_gives_the_same_answer_as_the_function(operation):
    # The unfolding takes a colored net; every other operation is run on the mutex net.
    pnml = GUARDED if operation == "unfold" else MUTEX_PNML
    request = EngineRequest(
        kind="analysis",
        net_id="n1",
        operation=operation,
        parameters={},
        limits=Limits(memory_mb=512, timeout_s=60),
    )
    report = registry.run_operation(
        engine="native", pnml=pnml, request=request, job_id=f"it-native-{operation}"
    )
    assert report.status == "ok"
    assert (report.tool_name, report.tool_version) == ("native", DEFAULT_ENGINES["native"].version)
    expected = perform(
        operation=operation,
        document=import_pnml(payload=pnml, limits=DocumentLimits()),
        net_id="n1",
        parameters={},
    )
    assert report.result == expected.result
    if operation == "unfold":
        from app.domain.pnml_export import render_pnml

        assert report.reduced_pnml == render_pnml(document=expected.reduced)


def test_an_unknown_operation_is_a_failure_with_a_reason_not_a_result():
    request = EngineRequest(
        kind="analysis", net_id="n1", operation="nope", limits=Limits(memory_mb=512, timeout_s=60)
    )
    report = registry.run_operation(
        engine="native", pnml=MUTEX_PNML, request=request, job_id="it-native-unknown"
    )
    assert (report.status, report.error_code) == ("failed", "adapter_exception")
    assert report.result is None


def test_a_reduction_in_the_container_writes_the_reduced_net_the_function_builds():
    from app.domain.pnml_export import render_pnml
    from tests.api.test_operations_api import TWIN_PLACES

    parameters = {"protected": []}
    request = EngineRequest(
        kind="reduction",
        net_id="n1",
        operation="fuse-parallel-places",
        parameters=parameters,
        limits=Limits(memory_mb=512, timeout_s=60),
    )
    report = registry.run_operation(
        engine="native", pnml=TWIN_PLACES, request=request, job_id="it-native-reduction"
    )
    assert report.status == "ok"
    expected = perform(
        operation="fuse-parallel-places",
        document=import_pnml(payload=TWIN_PLACES, limits=DocumentLimits()),
        net_id="n1",
        parameters=parameters,
    )
    assert report.result == expected.result
    assert report.reduced_pnml == render_pnml(document=expected.reduced)
