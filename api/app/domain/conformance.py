"""Cross-engine conformance: the same questions to every engine, side by side.

A case is a net, a formula and a verdict established independently of the engines (by the contest
or by hand). The matrix says, for each engine, whether it agreed, was wrong, or gave no answer
within its limits. A wrong answer, or two engines answering TRUE and FALSE for one case, is a
failure to triage, never resolved silently (CLAUDE.md, domain rule 8).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from .formula import Formula, Logic
from .models import DomainModel, Verdict


class CaseSpec(DomainModel):
    """A case as written in a cases file; the net and the formula are found from it."""

    id: str = Field(min_length=1)
    net: str
    expected: Literal["TRUE", "FALSE"]
    source: str
    # A formula written in the platform's text syntax...
    formula_text: str | None = None
    logic: Logic | None = None
    # ...or one of the contest's properties, by examination and id, from a ``<Examination>.xml``
    # file next to the net.
    examination: str | None = None
    property_id: str | None = None


class ConformanceCase(DomainModel):
    """A case ready to run."""

    case_id: str
    net: str
    pnml: bytes
    formula: Formula
    expected: Verdict
    source: str


class CellOutcome(StrEnum):
    """How one engine did on one case."""

    AGREES = "agrees"
    WRONG = "wrong"
    NO_ANSWER = "no_answer"


class MatrixCell(DomainModel):
    """One engine's answer to one case."""

    engine: str
    verdict: Verdict
    outcome: CellOutcome
    time_s: float = 0.0
    warnings: tuple[str, ...] = ()


class MatrixRow(DomainModel):
    """One case across the engines."""

    case_id: str
    net: str
    source: str
    expected: Verdict
    cells: tuple[MatrixCell, ...]
    # Two engines gave opposite definite verdicts: needs triage even if one of them is right.
    engines_disagree: bool


class ConformanceMatrix(DomainModel):
    """The result of a conformance run."""

    engines: tuple[str, ...]
    rows: tuple[MatrixRow, ...]

    def failures(self) -> tuple[MatrixRow, ...]:
        """Return the rows with a wrong answer or a disagreement between engines."""
        return tuple(
            row
            for row in self.rows
            if row.engines_disagree or any(c.outcome is CellOutcome.WRONG for c in row.cells)
        )


def classify(*, expected: Verdict, verdict: Verdict) -> CellOutcome:
    """Compare an answer with the established verdict; only TRUE and FALSE are answers."""
    if verdict not in {Verdict.TRUE, Verdict.FALSE}:
        return CellOutcome.NO_ANSWER
    return CellOutcome.AGREES if verdict is expected else CellOutcome.WRONG


def build_row(*, case: ConformanceCase, cells: tuple[MatrixCell, ...]) -> MatrixRow:
    """Assemble the row of a case from the cells of the engines."""
    definite = {cell.verdict for cell in cells if cell.verdict in {Verdict.TRUE, Verdict.FALSE}}
    return MatrixRow(
        case_id=case.case_id,
        net=case.net,
        source=case.source,
        expected=case.expected,
        cells=cells,
        engines_disagree=len(definite) > 1,
    )


def render_markdown(*, matrix: ConformanceMatrix) -> str:
    """Write the matrix as a Markdown table: one row per case, one column per engine.

    A cell is the verdict, followed by ``!`` when it is wrong; a row that needs triage is marked.
    """
    header = "| case | expected | " + " | ".join(matrix.engines) + " | triage |"
    lines = [header, "|" + "---|" * (len(matrix.engines) + 3)]
    for row in matrix.rows:
        by_engine = {cell.engine: cell for cell in row.cells}
        shown = []
        for engine in matrix.engines:
            cell = by_engine.get(engine)
            if cell is None:
                shown.append("-")
            else:
                shown.append(
                    cell.verdict.value + ("!" if cell.outcome is CellOutcome.WRONG else "")
                )
        triage = "yes" if row in matrix.failures() else ""
        lines.append(
            f"| {row.case_id} | {row.expected.value} | " + " | ".join(shown) + f" | {triage} |"
        )
    return "\n".join(lines) + "\n"
