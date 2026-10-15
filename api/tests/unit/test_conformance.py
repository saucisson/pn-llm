from pathlib import Path

import pytest

from app.application.conformance import ConformanceService
from app.conformance import load_cases
from app.domain.conformance import (
    CellOutcome,
    ConformanceCase,
    MatrixCell,
    build_row,
    classify,
    render_markdown,
)
from app.domain.engine_contract import EngineFormulaResult, EngineReport, ReportedResult
from app.domain.errors import InvalidRequestError
from app.domain.formula_text import formula_from_text
from app.domain.models import EngineInfo, Limits, Verdict
from tests.support import MUTEX_PNML

CASES_FILE = Path(__file__).resolve().parents[1] / "corpus" / "conformance.json"


def case(*, case_id="c1", expected=Verdict.TRUE, net="n"):
    return ConformanceCase(
        case_id=case_id,
        net=net,
        pnml=MUTEX_PNML,
        formula=formula_from_text(
            text='"crit1" >= 1', formula_id=case_id, logic="state", gloss="", origin="template"
        ),
        expected=expected,
        source="by hand",
    )


class FakeGateway:
    """Engines that answer from a table: engine -> verdict (None: no result at all)."""

    def __init__(self, *, answers):
        self._answers = answers

    def list_engines(self):
        return tuple(
            EngineInfo(name=name, version="1", logics=("state",), available=name != "absent")
            for name in (*self._answers, "dummy", "absent")
        )

    def run(self, *, engine, pnml, request, job_id):
        verdict = self._answers[engine]
        results = (
            ()
            if verdict is None
            else tuple(
                ReportedResult(result=EngineFormulaResult(id=f.id, verdict=verdict, time_s=1.5))
                for f in request.formulas
            )
        )
        return EngineReport(status="ok", results=results)


def test_only_true_and_false_are_answers():
    assert classify(expected=Verdict.TRUE, verdict=Verdict.TRUE) is CellOutcome.AGREES
    assert classify(expected=Verdict.TRUE, verdict=Verdict.FALSE) is CellOutcome.WRONG
    for non_answer in (Verdict.UNKNOWN, Verdict.TIMEOUT, Verdict.OOM, Verdict.ERROR):
        assert classify(expected=Verdict.FALSE, verdict=non_answer) is CellOutcome.NO_ANSWER


def test_engines_that_contradict_each_other_are_flagged_even_when_one_is_right():
    cells = tuple(
        MatrixCell(
            engine=name, verdict=verdict, outcome=classify(expected=Verdict.TRUE, verdict=verdict)
        )
        for name, verdict in (("a", Verdict.TRUE), ("b", Verdict.FALSE), ("c", Verdict.UNKNOWN))
    )
    assert build_row(case=case(), cells=cells).engines_disagree is True
    quiet = build_row(case=case(), cells=cells[::2])
    assert quiet.engines_disagree is False


def test_the_service_builds_the_matrix_and_reports_triage_rows():
    service = ConformanceService(
        engines=FakeGateway(answers={"good": Verdict.TRUE, "bad": Verdict.FALSE, "mute": None})
    )
    matrix = service.run(
        cases=(case(case_id="c1"), case(case_id="c2")),
        engines=("good", "bad", "mute"),
        limits=Limits(),
    )
    row = matrix.rows[0]
    assert [c.outcome for c in row.cells] == [
        CellOutcome.AGREES,
        CellOutcome.WRONG,
        CellOutcome.NO_ANSWER,
    ]
    assert row.cells[2].verdict is Verdict.ERROR  # an engine with no result is an error, not FALSE
    assert row.cells[2].warnings == ("no_result",)
    assert row.cells[0].time_s == 1.5
    assert len(matrix.failures()) == 2


def test_a_clean_run_has_no_failure_and_a_readable_table():
    service = ConformanceService(engines=FakeGateway(answers={"good": Verdict.TRUE}))
    matrix = service.run(cases=(case(),), engines=("good",), limits=Limits())
    assert matrix.failures() == ()
    table = render_markdown(matrix=matrix)
    assert table.splitlines()[0] == "| case | expected | good | triage |"
    assert "| c1 | TRUE | TRUE |  |" in table


def test_a_wrong_answer_is_marked_in_the_table():
    service = ConformanceService(engines=FakeGateway(answers={"bad": Verdict.FALSE}))
    table = render_markdown(matrix=service.run(cases=(case(),), engines=("bad",), limits=Limits()))
    assert "| c1 | TRUE | FALSE! | yes |" in table


def test_available_engines_leave_out_the_dummy_and_the_missing_images():
    service = ConformanceService(engines=FakeGateway(answers={"tapaal": None, "itstools": None}))
    assert service.available_engines() == ("itstools", "tapaal")


def test_the_bundled_cases_load_with_their_nets_and_formulas():
    cases = load_cases(path=CASES_FILE)
    assert len(cases) > 40
    assert {c.expected for c in cases} == {Verdict.TRUE, Verdict.FALSE}
    assert len({c.case_id for c in cases}) == len(cases)
    assert all(c.formula.id == c.case_id and c.pnml for c in cases)
    assert {c.formula.logic for c in cases} == {"state", "ctl", "ltl"}


def test_a_case_that_names_no_formula_is_refused(tmp_path):
    (tmp_path / "n.pnml").write_bytes(MUTEX_PNML)
    path = tmp_path / "cases.json"
    path.write_text('[{"id": "x", "net": "n.pnml", "expected": "TRUE", "source": "s"}]')
    with pytest.raises(InvalidRequestError):
        load_cases(path=path)


def test_a_contest_property_that_is_not_in_its_file_is_refused(tmp_path):
    (tmp_path / "n.pnml").write_bytes(MUTEX_PNML)
    (tmp_path / "CTLCardinality.xml").write_text(
        '<property-set xmlns="http://mcc.lip6.fr/"><property><id>a</id><description/>'
        "<formula><all-paths><globally><is-fireable><transition>t</transition></is-fireable>"
        "</globally></all-paths></formula></property></property-set>"
    )
    path = tmp_path / "cases.json"
    path.write_text(
        '[{"id": "x", "net": "n.pnml", "expected": "TRUE", "source": "s",'
        ' "examination": "CTLCardinality", "property_id": "zzz"}]'
    )
    with pytest.raises(InvalidRequestError, match="no property"):
        load_cases(path=path)
