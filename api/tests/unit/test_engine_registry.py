import json

import pytest

from app.domain.engine_contract import EngineRequest
from app.domain.errors import InvalidRequestError
from app.domain.models import Verdict
from app.infrastructure.docker_runner import (
    DockerRunner,
    DockerTimeoutError,
    DockerUnavailableError,
    RunOutcome,
)
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from tests.support import engine_envelope, make_formula, make_request

CHECK = make_request(
    formulas=[make_formula(formula_id="f1"), make_formula(formula_id="f2")], engine="itstools"
)
REQUEST = EngineRequest(net_id="n", formulas=CHECK.formulas, limits=CHECK.limits)


class FakeDocker(DockerRunner):
    """Stands in for the Docker process boundary: records runs and writes a canned output."""

    def __init__(self, *, images=(), output=None, error=None, outcome=None, files=None):
        self.images = set(images)
        self.output = output
        self.files = files or {}
        self.error = error
        self.runs = []
        self.stopped = []
        self.outcome = outcome or RunOutcome(exit_code=0, oom_killed=False, log_tail="")

    def image_present(self, *, image):
        return image in self.images

    def run(self, *, image, job_id, work_dir, limits):
        self.runs.append(
            {
                "image": image,
                "job_id": job_id,
                "limits": limits,
                "net": (work_dir / "input" / "net.pnml").read_bytes(),
                "request": json.loads((work_dir / "input" / "request.json").read_text()),
            }
        )
        if self.error is not None:
            raise self.error
        if self.output is not None:
            (work_dir / "output" / "result.json").write_text(json.dumps(self.output))
        for name, content in self.files.items():
            (work_dir / "output" / name).write_text(content)
        return self.outcome

    def stop(self, *, job_id):
        self.stopped.append(job_id)


def registry(*, docker=None):
    return EngineRegistry(specs=DEFAULT_ENGINES, docker=docker or FakeDocker())


# ---- catalog --------------------------------------------------------------------------------


def test_registry_contains_the_mcc_2026_tools():
    assert {"itstools", "tapaal", "smpt", "tedd", "petrivet", "ty", "dummy"} <= set(DEFAULT_ENGINES)


def test_the_engines_that_read_only_p_t_nets_say_so():
    colored = {name for name, spec in DEFAULT_ENGINES.items() if spec.colored}
    # smpt has no colored front end in its image (no mcc unfolder), petrivet reads P/T only.
    assert {"petrivet", "smpt"}.isdisjoint(colored)
    assert {"itstools", "tapaal", "tedd", "ty"} <= colored


def test_listing_reports_availability():
    docker = FakeDocker(images={"pn-llm-verif/tapaal:4.4.2"})
    available = {e.name for e in registry(docker=docker).list_engines() if e.available}
    assert available == {"dummy", "tapaal"}


def test_is_known():
    assert registry().is_known(name="tapaal")
    assert not registry().is_known(name="auto")  # "auto" is a request value, not an engine
    assert not registry().is_known(name="nope")


def test_auto_falls_back_to_dummy_when_no_image_is_built():
    assert registry().choose(requested="auto") == "dummy"


def test_auto_picks_the_first_available_real_engine():
    docker = FakeDocker(images={"pn-llm-verif/smpt:5.0-82206dd", "pn-llm-verif/ty:latest"})
    assert registry(docker=docker).choose(requested="auto") == "smpt"


def test_an_explicit_engine_is_returned_as_is():
    assert registry().choose(requested="tapaal") == "tapaal"


# ---- running --------------------------------------------------------------------------------


def test_unknown_engine_cannot_run():
    with pytest.raises(InvalidRequestError):
        registry().run(engine="nope", pnml=b"", request=REQUEST, job_id="j1")


def verdicts(report):
    return [(item.result.id, item.result.verdict) for item in report.results]


def test_dummy_engine_never_claims_a_verdict():
    report = registry().run(engine="dummy", pnml=b"", request=REQUEST, job_id="j1")
    assert [v for _, v in verdicts(report)] == [Verdict.UNKNOWN, Verdict.UNKNOWN]
    assert all("dummy_engine_no_verification" in r.result.warnings for r in report.results)
    assert report.tool_version == "0.1"


def test_container_results_are_parsed_with_the_tool_version_and_rendering():
    output = engine_envelope(
        results=[
            {"id": "f1", "verdict": "TRUE", "rendered": "AG p"},
            {"id": "f2", "verdict": "FALSE", "time_s": 1.5, "warnings": ["w"]},
        ]
    )
    report = registry(docker=FakeDocker(output=output)).run(
        engine="itstools", pnml=b"<pnml/>", request=REQUEST, job_id="j1"
    )
    assert verdicts(report) == [("f1", Verdict.TRUE), ("f2", Verdict.FALSE)]
    assert (report.tool_name, report.tool_version, report.status) == ("itstools", "9", "ok")
    assert report.results[0].result.rendered == "AG p"
    assert report.results[1].result.time_s == 1.5


def test_the_engine_receives_the_net_the_request_and_the_limits():
    docker = FakeDocker(output=engine_envelope(results=[]))
    registry(docker=docker).run(engine="itstools", pnml=b"<pnml/>", request=REQUEST, job_id="j1")
    (run,) = docker.runs
    assert run["image"] == DEFAULT_ENGINES["itstools"].image
    assert run["net"] == b"<pnml/>"
    assert run["request"]["schema_version"] == "1.0"
    assert run["request"]["kind"] == "check"
    assert run["request"]["net_id"] == "n"
    assert [f["id"] for f in run["request"]["formulas"]] == ["f1", "f2"]
    assert run["request"]["formulas"][0]["ast"]["op"] == "tokens"
    assert (run["limits"].timeout_s, run["limits"].memory_mb) == (300, 4096)


def test_traces_cited_by_results_are_loaded():
    trace = json.dumps({"steps": [{"transition": "t1"}, {"transition": "t2"}], "loop_start": 1})
    output = engine_envelope(results=[{"id": "f1", "verdict": "FALSE", "trace": "trace_f1.json"}])
    docker = FakeDocker(output=output, files={"trace_f1.json": trace})
    report = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST, job_id="j1")
    loaded = report.results[0].trace
    assert [step.transition for step in loaded.steps] == ["t1", "t2"]
    assert loaded.loop_start == 1


def test_an_unreadable_trace_keeps_the_verdict_and_says_so():
    output = engine_envelope(results=[{"id": "f1", "verdict": "FALSE", "trace": "trace_f1.json"}])
    docker = FakeDocker(output=output, files={"trace_f1.json": "not json"})
    report = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST, job_id="j1")
    assert report.results[0].trace is None
    assert report.results[0].result.warnings == ("unreadable_trace",)


def test_a_trace_name_cannot_leave_the_output_directory():
    output = engine_envelope(results=[{"id": "f1", "verdict": "FALSE", "trace": "../x.json"}])
    report = registry(docker=FakeDocker(output=output)).run(
        engine="itstools", pnml=b"", request=REQUEST, job_id="j1"
    )
    assert report.status == "failed"
    assert report.error_code == "unreadable_result_json"


def test_a_failed_envelope_is_a_failed_report_with_its_error_code():
    output = engine_envelope(
        results=[], status="failed", error={"code": "unsupported_net", "message": "x"}
    )
    report = registry(docker=FakeDocker(output=output)).run(
        engine="itstools", pnml=b"", request=REQUEST, job_id="j1"
    )
    assert (report.status, report.error_code) == ("failed", "unsupported_net")


def test_garbage_in_result_json_is_a_failed_report():
    docker = FakeDocker(files={"result.json": "{not json"})
    report = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST, job_id="j1")
    assert (report.status, report.error_code) == ("failed", "unreadable_result_json")


def test_a_missing_result_file_is_an_error_never_a_verdict():
    report = registry(docker=FakeDocker()).run(
        engine="itstools", pnml=b"", request=REQUEST, job_id="j1"
    )
    assert {v for _, v in verdicts(report)} == {Verdict.ERROR}
    assert report.results[0].result.warnings == ("no_result_file_exit_0",)


def test_a_timeout_is_reported_for_every_formula():
    docker = FakeDocker(error=DockerTimeoutError("itstools"))
    report = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST, job_id="j1")
    assert [v for _, v in verdicts(report)] == [Verdict.TIMEOUT, Verdict.TIMEOUT]


def test_an_unreachable_docker_daemon_is_an_error():
    docker = FakeDocker(error=DockerUnavailableError("no daemon"))
    report = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST, job_id="j1")
    assert {v for _, v in verdicts(report)} == {Verdict.ERROR}
    assert report.results[0].result.warnings == ("docker_unavailable",)


def test_an_out_of_memory_kill_is_reported_as_oom_even_if_a_result_was_written():
    outcome = RunOutcome(exit_code=137, oom_killed=True, log_tail="")
    output = engine_envelope(results=[{"id": "f1", "verdict": "TRUE"}])
    docker = FakeDocker(output=output, outcome=outcome)
    report = registry(docker=docker).run(engine="itstools", pnml=b"", request=REQUEST, job_id="j1")
    assert [v for _, v in verdicts(report)] == [Verdict.OOM, Verdict.OOM]
    assert report.results[0].result.warnings == ("engine_out_of_memory",)


def test_a_failed_exit_without_result_is_an_error_naming_the_exit_code():
    outcome = RunOutcome(exit_code=2, oom_killed=False, log_tail="boom")
    report = registry(docker=FakeDocker(outcome=outcome)).run(
        engine="itstools", pnml=b"", request=REQUEST, job_id="j1"
    )
    assert report.results[0].result.warnings == ("no_result_file_exit_2",)


def test_stopping_a_job_reaches_the_runner():
    docker = FakeDocker()
    registry(docker=docker).stop(job_id="j7")
    assert docker.stopped == ["j7"]
