"""Routes about formulas."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.domain.contract import Envelope
from app.domain.formula_check import FormulaReport, FormulaValidationRequest

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
