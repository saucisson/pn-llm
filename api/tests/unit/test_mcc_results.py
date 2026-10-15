import pytest

from app.domain.errors import InvalidRequestError
from app.domain.mcc import MccNetType
from app.domain.mcc_results import (
    HEADER,
    RunOutcome,
    RunSample,
    normalize_tool,
    parse_results,
    summarize_runs,
)

ROWS = (
    "petrivet,Big-PT-10,CTLFireability,1,OK,OK,DNC,-,73.6,222,11,10.1,normal,r1",
    "itstools,Big-PT-10,CTLFireability,4,OK,OK,16 BOOL:TRUE BOOL:FALSE,STRUCTURAL SCC_TEST,"
    "100.5,2739.00,1500.50,0,normal,r2",
    "itstools,Big-PT-20,CTLFireability,4,DNF,OK,DNF,-,10,1,3600000,0,timeout,r3",
    "TY,Big-PT-20,CTLFireability,4,OK,MOVF,CC,-,99999,5,6,0,normal,r4",
    "gold2025,Odd,StateSpace,1,OK,OK,4 NUM:1 NUM:2 NUM:3 NUM:4,-,1,1,2,0,normal,r5",
)


def runs():
    return list(parse_results(lines=(f"### {HEADER}", *ROWS), year=2026))


def test_tool_names_lose_their_year_and_case_and_references_are_marked():
    assert normalize_tool(name="gold2025") == ("gold", True)
    assert normalize_tool(name="BVT-2026") == ("bvt", True)
    assert normalize_tool(name="TY") == ("ty", False)
    assert normalize_tool(name="itstools") == ("itstools", False)


def test_rows_keep_the_contests_own_classes_and_never_become_a_verdict():
    petrivet, itstools, timeout, memory, gold = runs()
    assert petrivet.outcome is RunOutcome.DID_NOT_COMPUTE
    assert petrivet.results == ""
    assert (itstools.outcome, itstools.results) == (RunOutcome.COMPUTED, "16 BOOL:TRUE BOOL:FALSE")
    assert (itstools.family, itstools.net_type, itstools.cores) == ("Big", MccNetType.PT, 4)
    assert itstools.techniques == ("STRUCTURAL", "SCC_TEST")
    assert itstools.time_ms == 1500.5
    assert (timeout.outcome, timeout.timed_out) == (RunOutcome.DID_NOT_FINISH, True)
    assert (memory.outcome, memory.out_of_memory) == (RunOutcome.CANNOT_COMPUTE, True)
    assert (gold.reference, gold.family, gold.net_type) == (True, "Odd", None)


def test_statistics_count_every_run_and_take_the_median_of_computed_ones():
    samples = (RunSample(**run.model_dump(include=set(RunSample.model_fields))) for run in runs())
    by_tool = {s.tool: s for s in summarize_runs(samples=samples) if s.family == "Big"}
    assert by_tool["itstools"].runs == 2
    assert (by_tool["itstools"].computed, by_tool["itstools"].timeouts) == (1, 1)
    assert by_tool["itstools"].success_rate == 0.5
    assert by_tool["itstools"].median_time_ms == 1500.5
    assert by_tool["petrivet"].median_time_ms is None
    assert by_tool["petrivet"].success_rate == 0
    assert by_tool["ty"].out_of_memory == 1


@pytest.mark.parametrize(
    "lines",
    [
        [],
        ["not,the,header"],
        [f"### {HEADER}", "itstools,Big-PT-10"],
        [f"### {HEADER}", "itstools,Big-PT-10,X,notanumber,OK,OK,DNC,-,1,1,1,0,normal,r"],
    ],
)
def test_an_unexpected_file_is_refused_as_a_whole(lines):
    with pytest.raises(InvalidRequestError):
        list(parse_results(lines=lines, year=2026))


def test_a_run_published_twice_under_one_id_is_kept_twice():
    rerun = ROWS[0].replace(",222,", ",223,")
    found = list(parse_results(lines=(f"### {HEADER}", ROWS[0], rerun), year=2026))
    assert [run.cpu_ms for run in found] == [222, 223]
