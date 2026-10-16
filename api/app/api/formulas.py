"""Routes about formulas."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.domain.contract import Envelope
from app.domain.formula_check import FormulaReport, FormulaValidationRequest
from app.domain.models import DomainModel
from app.domain.patterns import PATTERNS, PatternInfo, PatternRequest

from .deps import FormulasDep
from .envelopes import wrap

router = APIRouter(prefix="/v1/formulas", tags=["formulas"])


@router.post("/validate")
def validate_formula(
    *, body: FormulaValidationRequest, formulas: FormulasDep
) -> Envelope[FormulaReport]:
    """Parse and check a formula on a net: errors, warnings, atom classes, canonical text."""
    started = time.perf_counter()
    return wrap(
        tool="formula.validate",
        net_id=body.net_id,
        started=started,
        data=formulas.validate(request=body),
    )


class PatternFormulaRequest(DomainModel):
    """Body of ``POST /v1/formulas/from-pattern``."""

    net_id: str
    id: str = "f1"
    pattern: PatternRequest


@router.get("/patterns")
def list_patterns() -> Envelope[tuple[PatternInfo, ...]]:
    """List the specification patterns and the parameters each takes."""
    started = time.perf_counter()
    return wrap(tool="formula.patterns", net_id=None, started=started, data=PATTERNS)


@router.post("/from-pattern")
def formula_from_pattern(
    *, body: PatternFormulaRequest, formulas: FormulasDep
) -> Envelope[FormulaReport]:
    """Build the formula of a pattern (absence, response, bound, ...) and check it on the net."""
    started = time.perf_counter()
    return wrap(
        tool="formula.from_pattern",
        net_id=body.net_id,
        started=started,
        data=formulas.from_pattern(net_id=body.net_id, request=body.pattern, formula_id=body.id),
    )
