"""The conformance suite against every engine image built here, on the hand-made cases.

The contest cases take minutes per engine: run them with
``python -m app.conformance --cases tests/corpus/conformance.json --markdown``.
"""

from pathlib import Path

import pytest

from app.application.conformance import ConformanceService
from app.conformance import load_cases
from app.domain.conformance import CellOutcome
from app.domain.models import Limits
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry

CASES_FILE = Path(__file__).resolve().parents[1] / "corpus" / "conformance.json"

pytestmark = pytest.mark.docker


def test_no_built_engine_is_wrong_or_contradicts_another_on_the_hand_made_cases():
    service = ConformanceService(
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    )
    engines = service.available_engines()
    if not engines:
        pytest.skip("no engine image is built here")
    cases = tuple(c for c in load_cases(path=CASES_FILE) if c.net.startswith("hand/"))
    matrix = service.run(cases=cases, engines=engines, limits=Limits(timeout_s=120, memory_mb=1024))
    assert matrix.failures() == ()
    assert any(cell.outcome is CellOutcome.AGREES for row in matrix.rows for cell in row.cells)
