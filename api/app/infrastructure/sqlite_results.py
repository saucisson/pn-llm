"""The contest's published runs in the SQLite database."""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Iterable, Iterator

from app.domain.mcc_results import (
    MccRun,
    ResultFileInfo,
    ResultSetInfo,
    RunOutcome,
    RunSample,
    ToolRate,
)

from .sqlite_database import SqliteDatabase

BATCH = 5_000


class SqliteResults(SqliteDatabase):
    """Implements the ``ResultsRepository`` port."""

    def replace_result_set(
        self, *, year: int, file: ResultFileInfo, runs: Iterable[MccRun]
    ) -> ResultSetInfo:
        """Store the runs of a year in place of the ones stored for it, all or nothing."""
        stored = 0
        with self._connection() as conn:
            conn.execute("DELETE FROM mcc_runs WHERE year=?", (year,))
            conn.execute("DELETE FROM mcc_result_sets WHERE year=?", (year,))
            conn.execute(
                "INSERT INTO mcc_result_sets(year, url, sha256, runs) VALUES (?, ?, ?, 0)",
                (year, file.url, file.sha256),
            )
            iterator = iter(runs)
            while batch := list(itertools.islice(iterator, BATCH)):
                conn.executemany(
                    "INSERT INTO mcc_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            run.year,
                            run.run_id,
                            run.tool,
                            run.reference,
                            run.instance,
                            run.family,
                            run.net_type,
                            run.examination,
                            run.cores,
                            run.outcome,
                            run.results,
                            " ".join(run.techniques),
                            run.memory_mb,
                            run.cpu_ms,
                            run.time_ms,
                            run.timed_out,
                            run.out_of_memory,
                        )
                        for run in batch
                    ],
                )
                stored += len(batch)
            conn.execute("UPDATE mcc_result_sets SET runs=? WHERE year=?", (stored, year))
        return ResultSetInfo(year=year, url=file.url, sha256=file.sha256, runs=stored)

    def samples(
        self, *, tool: str | None, examination: str | None, family: str | None
    ) -> Iterator[RunSample]:
        """Yield the runs matching the filters, in no particular order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT tool, examination, family, outcome, time_ms, timed_out, out_of_memory"
                " FROM mcc_runs WHERE (? IS NULL OR tool=?) AND (? IS NULL OR examination=?)"
                " AND (? IS NULL OR family=?)",
                (tool, tool, examination, examination, family, family),
            )
            for row in rows:
                yield RunSample(
                    tool=row["tool"],
                    examination=row["examination"],
                    family=row["family"],
                    outcome=RunOutcome(row["outcome"]),
                    time_ms=row["time_ms"],
                    timed_out=bool(row["timed_out"]),
                    out_of_memory=bool(row["out_of_memory"]),
                )

    def result_sets(self) -> tuple[ResultSetInfo, ...]:
        """Return the stored result sets, by year."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM mcc_result_sets ORDER BY year").fetchall()
        return tuple(ResultSetInfo.model_validate(dict(row)) for row in rows)

    def tool_rates(self, *, examinations: tuple[str, ...]) -> tuple[ToolRate, ...]:
        """Return, per engine and examination, the runs and how many computed, with median time.

        The references of the contest (virtual best tools) are not engines and are left out.
        """
        marks = ",".join("?" for _ in examinations)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT tool, examination, outcome, time_ms FROM mcc_runs"  # noqa: S608 - placeholders only
                f" WHERE reference=0 AND examination IN ({marks})",
                examinations,
            ).fetchall()
        runs: dict[tuple[str, str], int] = {}
        times: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            key = (row["tool"], row["examination"])
            runs[key] = runs.get(key, 0) + 1
            if row["outcome"] == RunOutcome.COMPUTED.value:
                times.setdefault(key, []).append(row["time_ms"])
        return tuple(
            ToolRate(
                tool=tool,
                examination=examination,
                runs=count,
                computed=len(times.get((tool, examination), ())),
                median_time_ms=(
                    statistics.median(times[(tool, examination)])
                    if (tool, examination) in times
                    else None
                ),
            )
            for (tool, examination), count in sorted(runs.items())
        )
