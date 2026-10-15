import json

import pytest
from pnverif_engine import (
    AdapterAnswer,
    AdapterInput,
    normalize_verdict,
    read_request,
    run_adapter,
    write_failure,
    write_result,
)

from app.domain.contract import Envelope, ErrorInfo, ToolInfo
from app.domain.engine_contract import EngineCheckData, EngineRequest, EngineTrace
from app.domain.models import Verdict
from tests.support import make_formula, make_request


@pytest.fixture
def work_dir(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    check = make_request(
        formulas=[make_formula(formula_id="f1"), make_formula(formula_id="odd id/with:chars")]
    )
    request = EngineRequest(net_id="n1", formulas=check.formulas, limits=check.limits)
    (tmp_path / "input" / "request.json").write_text(request.model_dump_json())
    (tmp_path / "input" / "net.pnml").write_text("<pnml/>")
    return tmp_path


def read_envelope(work_dir):
    return Envelope[EngineCheckData].model_validate_json(
        (work_dir / "output" / "result.json").read_text()
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, Verdict.TRUE),
        (False, Verdict.FALSE),
        ("TRUE", Verdict.TRUE),
        (" Yes ", Verdict.TRUE),
        ("satisfied", Verdict.TRUE),
        ("FALSE", Verdict.FALSE),
        ("violated", Verdict.FALSE),
        ("CANNOT_COMPUTE", Verdict.UNKNOWN),
        ("timeout", Verdict.UNKNOWN),
        ("maybe", Verdict.UNKNOWN),
        ("", Verdict.UNKNOWN),
        (None, Verdict.UNKNOWN),
    ],
)
def test_only_clear_words_become_a_verdict_and_doubt_is_never_false(raw, expected):
    assert normalize_verdict(raw=raw) is expected


def test_the_request_is_read_and_validated(work_dir):
    assert read_request(work_dir=work_dir).net_id == "n1"


def test_a_check_writes_one_entry_per_formula_in_order_with_the_tool_version(work_dir):
    run_adapter(
        tool_name="t",
        tool_version="4.5",
        work_dir=work_dir,
        check=lambda given: (
            AdapterAnswer(formula_id="f1", verdict=Verdict.TRUE, rendered="AG p", time_s=0.5),
            AdapterAnswer(formula_id="odd id/with:chars", verdict=Verdict.FALSE),
        ),
    )
    envelope = read_envelope(work_dir)
    assert (envelope.tool.name, envelope.tool.version, envelope.status) == ("t", "4.5", "ok")
    assert envelope.net_id == "n1"
    assert [(r.id, r.verdict) for r in envelope.data.results] == [
        ("f1", Verdict.TRUE),
        ("odd id/with:chars", Verdict.FALSE),
    ]
    assert envelope.data.results[0].rendered == "AG p"


def test_traces_get_safe_file_names_whatever_the_formula_id(work_dir):
    run_adapter(
        tool_name="t",
        tool_version="1",
        work_dir=work_dir,
        check=lambda given: (
            AdapterAnswer(
                formula_id="odd id/with:chars",
                verdict=Verdict.FALSE,
                trace=("a", "b"),
                loop_start=1,
            ),
        ),
    )
    entries = read_envelope(work_dir).data.results
    assert entries[1].trace == "trace_1.json"
    trace = EngineTrace.model_validate_json((work_dir / "output" / "trace_1.json").read_text())
    assert [s.transition for s in trace.steps] == ["a", "b"]
    assert trace.loop_start == 1


def test_a_formula_the_tool_did_not_answer_is_an_error_and_an_unknown_one_is_dropped(work_dir):
    run_adapter(
        tool_name="t",
        tool_version="1",
        work_dir=work_dir,
        check=lambda given: (
            AdapterAnswer(formula_id="f1", verdict=Verdict.TRUE),
            AdapterAnswer(formula_id="stranger", verdict=Verdict.TRUE),
        ),
    )
    results = read_envelope(work_dir).data.results
    assert [r.id for r in results] == ["f1", "odd id/with:chars"]
    assert results[1].verdict is Verdict.ERROR
    assert results[1].warnings == ("no_answer_from_tool",)


def test_a_crash_of_the_tool_part_is_a_failed_envelope_not_a_missing_file(work_dir):
    def crashing(given: AdapterInput):
        raise RuntimeError("the tool exploded")

    run_adapter(tool_name="t", tool_version="1", work_dir=work_dir, check=crashing)
    envelope = read_envelope(work_dir)
    assert envelope.status == "failed"
    assert envelope.data is None
    assert envelope.error.code == "adapter_exception"
    assert "RuntimeError: the tool exploded" in envelope.error.message


def test_the_adapter_receives_the_request_and_the_paths(work_dir):
    seen = {}

    def check(given: AdapterInput):
        seen["net"] = given.net_path.read_text()
        seen["limits"] = given.request.limits.timeout_s
        seen["out"] = given.output_dir
        return ()

    run_adapter(tool_name="t", tool_version="1", work_dir=work_dir, check=check)
    assert seen == {"net": "<pnml/>", "limits": 300, "out": work_dir / "output"}


def test_a_failure_can_be_written_directly(work_dir):
    request = read_request(work_dir=work_dir)
    write_failure(
        output_dir=work_dir / "output",
        request=request,
        tool=ToolInfo(name="t", version="1"),
        error=ErrorInfo(code="unsupported_net", message="colored nets are not supported"),
        elapsed_s=0.1,
    )
    assert json.loads((work_dir / "output" / "result.json").read_text())["status"] == "failed"


def test_results_can_be_written_directly(work_dir):
    request = read_request(work_dir=work_dir)
    write_result(
        output_dir=work_dir / "output",
        request=request,
        tool=ToolInfo(name="t", version="1"),
        answers=(),
        elapsed_s=0.0,
    )
    assert {r.verdict for r in read_envelope(work_dir).data.results} == {Verdict.ERROR}
