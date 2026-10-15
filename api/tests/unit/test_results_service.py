import pytest

from app.application.results import ResultsService
from app.domain.contract import PageRequest
from app.domain.errors import InvalidRequestError
from app.domain.mcc_results import HEADER, ResultFileInfo
from app.infrastructure.sqlite_results import SqliteResults
from tests.unit.test_mcc_results import ROWS


class FakeContest:
    def __init__(self, *, lines):
        self._lines = lines

    def result_file(self):
        return ResultFileInfo(url="https://example.org/GlobalSummary.csv.tar.gz", sha256="ab" * 32)

    def result_lines(self):
        yield from self._lines


@pytest.fixture
def results(settings):
    return ResultsService(results=SqliteResults(path=settings.database_path))


def contest(*, rows=ROWS):
    return FakeContest(lines=(f"### {HEADER}", *rows))


def test_import_stores_the_runs_with_their_provenance(results):
    info = results.import_results(source=contest(), year=2026)
    assert (info.year, info.runs) == (2026, 5)
    assert results.result_sets() == (info,)
    assert info.url.endswith("GlobalSummary.csv.tar.gz")


def test_importing_again_replaces_instead_of_duplicating(results):
    results.import_results(source=contest(), year=2026)
    results.import_results(source=contest(rows=ROWS[:2]), year=2026)
    assert results.result_sets()[0].runs == 2
    found = results.statistics(tool=None, examination=None, family=None, page=PageRequest(limit=50))
    assert sum(s.runs for s in found.items) == 2


def test_a_broken_file_changes_nothing(results):
    results.import_results(source=contest(), year=2026)
    with pytest.raises(InvalidRequestError):
        results.import_results(source=contest(rows=(*ROWS, "broken")), year=2026)
    assert results.result_sets()[0].runs == 5


def test_statistics_can_be_filtered_and_are_paged(results):
    results.import_results(source=contest(), year=2026)
    only = results.statistics(
        tool="itstools", examination="CTLFireability", family="Big", page=PageRequest(limit=50)
    )
    assert [(s.tool, s.runs) for s in only.items] == [("itstools", 2)]
    first = results.statistics(tool=None, examination=None, family=None, page=PageRequest(limit=2))
    assert first.page.total == 4  # five runs, grouped by family, examination and tool
    assert first.page.next_cursor is not None
