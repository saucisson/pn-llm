"""Use cases about the contest's published results."""

from __future__ import annotations

from app.domain.contract import PageRequest
from app.domain.mcc_results import (
    ResultSetInfo,
    RunStatistics,
    parse_results,
    summarize_runs,
)
from app.domain.pagination import Paged, paginate

from .ports import MccSource, ResultsRepository


class ResultsService:
    """Import the published results and answer how reliable and fast each tool is."""

    def __init__(self, *, results: ResultsRepository) -> None:
        """Create the service over the results repository."""
        self._results = results

    def import_results(self, *, source: MccSource, year: int) -> ResultSetInfo:
        """Store the published runs of ``year``, replacing the ones already stored for it.

        Raises:
            InvalidRequestError: if the file is not the expected one; nothing is stored then.
        """
        file = source.result_file()
        return self._results.replace_result_set(
            year=year, file=file, runs=parse_results(lines=source.result_lines(), year=year)
        )

    def statistics(
        self,
        *,
        tool: str | None,
        examination: str | None,
        family: str | None,
        page: PageRequest,
    ) -> Paged[RunStatistics]:
        """Return a page of success rates and median times per family, examination and tool."""
        return paginate(
            items=summarize_runs(
                samples=self._results.samples(tool=tool, examination=examination, family=family)
            ),
            request=page,
        )

    def result_sets(self) -> tuple[ResultSetInfo, ...]:
        """Return where each stored set of results comes from."""
        return self._results.result_sets()
