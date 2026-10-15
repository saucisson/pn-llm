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


def test_asking_engines_not_to_reduce_gives_the_same_answers_including_with_next():
    service = ConformanceService(
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    )
    engines = service.available_engines()
    if not engines:
        pytest.skip("no engine image is built here")
    cases = tuple(c for c in load_cases(path=CASES_FILE) if c.net.startswith("hand/"))
    assert any("ltl-next" in c.case_id for c in cases)  # stutter sensitivity is covered
    limits = Limits(timeout_s=120, memory_mb=1024)
    reduced = service.run(cases=cases, engines=engines, limits=limits, reduce=True)
    plain = service.run(cases=cases, engines=engines, limits=limits, reduce=False)
    assert reduced.failures() == () == plain.failures()
    for with_reduction, without in zip(reduced.rows, plain.rows, strict=True):
        for a, b in zip(with_reduction.cells, without.cells, strict=True):
            assert a.verdict == b.verdict, (with_reduction.case_id, a.engine)
    # an engine that cannot switch its reductions off says so
    itstools = [c for row in plain.rows for c in row.cells if c.engine == "itstools"]
    assert all("reductions_cannot_be_disabled" in c.warnings for c in itstools)
