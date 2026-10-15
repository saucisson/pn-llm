"""The contest's published runs in the SQLite database."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator

from app.domain.mcc_results import MccRun, ResultFileInfo, ResultSetInfo, RunOutcome, RunSample

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
