import json

import pytest

from app.domain.errors import InvalidRequestError
from app.domain.models import Verdict
from app.infrastructure.docker_runner import DockerRunner, DockerTimeoutError
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from tests.support import make_formula, make_request

REQUEST = make_request(
    formulas=[make_formula(formula_id="f1"), make_formula(formula_id="f2")], engine="itstools"
)


class FakeDocker(DockerRunner):
    """Stands in for the Docker process boundary: records runs and writes a canned output."""

    def __init__(self, *, images=(), output=None, error=None):
        self.images = set(images)
        self.output = output
        self.error = error
        self.runs = []

    def image_present(self, *, image):
        return image in self.images

    def run(self, *, image, work_dir, limits):
        self.runs.append(
            {
                "image": image,
                "limits": limits,
                "net": (work_dir / "input" / "net.pnml").read_bytes(),
                "request": json.loads((work_dir / "input" / "request.json").read_text()),
            }
        )
        if self.error is not None:
            raise self.error
        if self.output is not None:
            (work_dir / "output" / "result.json").write_text(json.dumps(self.output))


def registry(*, docker=None):
    return EngineRegistry(specs=DEFAULT_ENGINES, docker=docker or FakeDocker())


# ---- catalog --------------------------------------------------------------------------------


def test_registry_contains_the_mcc_2026_tools():
    assert {"itstools", "tapaal", "smpt", "tedd", "petrivet", "ty", "dummy"} <= set(DEFAULT_ENGINES)


def test_petrivet_is_the_only_p_t_only_real_engine():
    colored = {name for name, spec in DEFAULT_ENGINES.items() if spec.colored}
    assert "petrivet" not in colored
    assert {"itstools", "tapaal", "smpt", "tedd", "ty"} <= colored


def test_listing_reports_availability():
    docker = FakeDocker(images={"pn-llm-verif/tapaal:latest"})
    available = {e.name for e in registry(docker=docker).list_engines() if e.available}
    assert available == {"dummy", "tapaal"}


def test_is_known():
    assert registry().is_known(name="tapaal")
    assert not registry().is_known(name="auto")  # "auto" is a request value, not an engine
    assert not registry().is_known(name="nope")


def test_auto_falls_back_to_dummy_when_no_image_is_built():
    assert registry().choose(requested="auto") == "dummy"


def test_auto_picks_the_first_available_real_engine():
    docker = FakeDocker(images={"pn-llm-verif/smpt:latest", "pn-llm-verif/ty:latest"})
    assert registry(docker=docker).choose(requested="auto") == "smpt"


def test_an_explicit_engine_is_returned_as_is():
    assert registry().choose(requested="tapaal") == "tapaal"


# ---- running --------------------------------------------------------------------------------


def test_unknown_engine_cannot_run():
    with pytest.raises(InvalidRequestError):
        registry().run(engine="nope", pnml=b"", request=REQUEST)


def test_dummy_engine_never_claims_a_verdict():
    results = registry().run(engine="dummy", pnml=b"", request=REQUEST)
    assert [r.verdict for r in results] == [Verdict.UNKNOWN, Verdict.UNKNOWN]
    assert all("dummy_engine_no_verification" in r.warnings for r in results)


def test_container_results_are_parsed():
    output = {
        "results": [
            {"id": "f1", "verdict": "TRUE", "engine": "itstools", "engine_version": "9"},
            {"id": "f2", "verdict": "FALSE", "engine": "itstools", "time_s": 1.5},
        ]
    }
    results = registry(docker=FakeDocker(output=output)).run(
        engine="itstools", pnml=b"<pnml/>", request=REQUEST
    )
    assert [(r.id, r.verdict) for r in results] == [("f1", Verdict.TRUE), ("f2", Verdict.FALSE)]
    assert results[0].engine_version == "9"


def test_the_engine_receives_the_net_the_request_and_the_limits():
    docker = FakeDocker(output={"results": []})
    registry(docker=docker).run(engine="itstools", pnml=b"<pnml/>", request=REQUEST)
    (run,) = docker.runs
    assert run["image"] == "pn-llm-verif/itstools:latest"
    assert run["net"] == b"<pnml/>"
    assert [f["id"] for f in run["request"]["formulas"]] == ["f1", "f2"]
    assert (run["limits"].timeout_s, run["limits"].memory_mb) == (300, 4096)


def test_a_missing_result_file_is_an_error_never_a_verdict():
    results = registry(docker=FakeDocker()).run(engine="itstools", pnml=b"", request=REQUEST)
    assert {r.verdict for r in results} == {Verdict.ERROR}
    assert "no_result_file" in results[0].warnings


def test_a_timeout_is_reported_for_every_formula():
    docker = FakeDocker(error=DockerTimeoutError("itstools"))
    results = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST)
    assert [r.verdict for r in results] == [Verdict.TIMEOUT, Verdict.TIMEOUT]


def test_missing_docker_is_an_error():
    docker = FakeDocker(error=FileNotFoundError())
    results = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST)
    assert {r.verdict for r in results} == {Verdict.ERROR}
    assert "docker_not_installed" in results[0].warnings
