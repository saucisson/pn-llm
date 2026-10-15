"""Published results of the Model Checking Contest: runs per tool, instance and examination.

A result is evidence about a tool, never a verdict of this platform: it keeps the contest's own
classes (computed, did not compute, did not finish, cannot compute) and never turns a missing
answer into FALSE (ADR 0006).
"""

from __future__ import annotations

import csv
import re
import statistics
from collections.abc import Iterable, Iterator
from enum import StrEnum

from .errors import InvalidRequestError
from .mcc import MccNetType, split_input_name
from .models import DomainModel

HEADER = (
    "tool,Input,Examination,nb cores,time flag,memory flag,results,techniques,max memory (MB),"
    "CPU (ms),Time (ms),i/o wait (ms),Status,run id"
)
REFERENCE_TOOLS = frozenset({"gold", "bvt"})
YEAR_SUFFIX = re.compile(r"[-_]?\d{4}$")
FAILURE_CODES = {"DNC": "did_not_compute", "DNF": "did_not_finish", "CC": "cannot_compute"}


class RunOutcome(StrEnum):
    """What a run produced, in the contest's own terms."""

    COMPUTED = "computed"
    DID_NOT_COMPUTE = "did_not_compute"
    DID_NOT_FINISH = "did_not_finish"
    CANNOT_COMPUTE = "cannot_compute"


class MccRun(DomainModel):
    """One run of a tool on an instance for an examination, as published."""

    year: int
    tool: str
    reference: bool
    instance: str
    family: str
    net_type: MccNetType | None
    examination: str
    cores: int
    outcome: RunOutcome
    results: str
    techniques: tuple[str, ...]
    memory_mb: float
    cpu_ms: float
    time_ms: float
    timed_out: bool
    out_of_memory: bool
    run_id: str


class ResultSetInfo(DomainModel):
    """Where a set of results comes from."""

    year: int
    url: str
    sha256: str
    runs: int


class ResultFileInfo(DomainModel):
    """The downloaded results file: where it came from and the hash of what was read."""

    url: str
    sha256: str


class RunSample(DomainModel):
    """The part of a run that statistics need."""

    tool: str
    examination: str
    family: str
    outcome: RunOutcome
    time_ms: float
    timed_out: bool
    out_of_memory: bool


class RunStatistics(DomainModel):
    """How a tool did on an examination over the instances of a family."""

    tool: str
    examination: str
    family: str
    runs: int
    computed: int
    timeouts: int
    out_of_memory: int
    success_rate: float
    median_time_ms: float | None


def normalize_tool(*, name: str) -> tuple[str, bool]:
    """Return the tool name used here and whether it is a reference, not an engine.

    The contest names tools with their year (``gold2025``) or in its own case (``TY``); here a
    tool is its lower-case name without year, so the same tool is one name across years.
    """
    tool = YEAR_SUFFIX.sub("", name).lower()
    return tool, tool in REFERENCE_TOOLS


def parse_results(*, lines: Iterable[str], year: int) -> Iterator[MccRun]:
    """Read the contest's ``GlobalSummary.csv`` lines into runs, one at a time.

    Some runs appear twice under the same run id (a re-run, often after a timeout); both rows
    are kept, because deciding which one counts would be our guess, not the contest's.

    Raises:
        InvalidRequestError: if the header is not the expected one, or a row is malformed; the
            whole file is refused rather than partly believed.
    """
    reader = csv.reader(lines)
    header = next(reader, None)
    if header is None or ",".join(header).lstrip("# ").strip() != HEADER:
        raise InvalidRequestError("Unexpected header in the results file")
    for number, row in enumerate(reader, start=2):
        try:
            tool, reference = normalize_tool(name=row[0])
            parts = split_input_name(name=row[1])
            code = row[6].strip()
            yield MccRun(
                year=year,
                tool=tool,
                reference=reference,
                instance=row[1],
                family=parts[0] if parts else row[1],
                net_type=parts[1] if parts else None,
                examination=row[2],
                cores=int(row[3]),
                outcome=RunOutcome(FAILURE_CODES.get(code, "computed")),
                results="" if code in FAILURE_CODES else code,
                techniques=tuple(row[7].split()) if row[7] != "-" else (),
                memory_mb=float(row[8]),
                cpu_ms=float(row[9]),
                time_ms=float(row[10]),
                timed_out=row[4] != "OK" or row[12] == "timeout",
                out_of_memory=row[5] != "OK",
                run_id=row[13],
            )
        except (IndexError, ValueError) as exc:
            raise InvalidRequestError(f"Malformed row {number} in the results file: {exc}") from exc


def summarize_runs(*, samples: Iterable[RunSample]) -> tuple[RunStatistics, ...]:
    """Group runs by family, examination and tool, and report success rate and median time.

    The median is over computed runs only; ``None`` when there are none.
    """
    groups: dict[tuple[str, str, str], list[RunSample]] = {}
    for sample in samples:
        groups.setdefault((sample.family, sample.examination, sample.tool), []).append(sample)
    summary = []
    for (family, examination, tool), group in sorted(groups.items()):
        times = [s.time_ms for s in group if s.outcome is RunOutcome.COMPUTED]
        summary.append(
            RunStatistics(
                tool=tool,
                examination=examination,
                family=family,
                runs=len(group),
                computed=len(times),
                timeouts=sum(s.timed_out for s in group),
                out_of_memory=sum(s.out_of_memory for s in group),
                success_rate=len(times) / len(group),
                median_time_ms=statistics.median(times) if times else None,
            )
        )
    return tuple(summary)
