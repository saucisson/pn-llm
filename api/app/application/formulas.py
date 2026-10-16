"""Use cases about formulas."""

from __future__ import annotations

from app.domain.errors import FormulaSyntaxError
from app.domain.formula_check import (
    AtomKinds,
    FormulaReport,
    FormulaValidationRequest,
    Issue,
    check_formula,
)
from app.domain.formula_text import formula_from_text
from app.domain.net_structure import build_structure
from app.domain.patterns import PatternRequest, instantiate

from .ports import NetRepository


class FormulaService:
    """Validate formulas against a net."""

    def __init__(self, *, nets: NetRepository) -> None:
        """Create the service over the net repository."""
        self._nets = nets

    def validate(self, *, request: FormulaValidationRequest) -> FormulaReport:
        """Parse (if given as text) and check a formula; problems are reported, not raised.

        Raises:
            NotFoundError: if the net is unknown.
        """
        stored = self._nets.load_net(net_id=request.net_id)
        formula = request.formula
        if formula is None:
            try:
                formula = formula_from_text(
                    text=request.text or "",
                    formula_id=request.id,
                    logic=request.logic,
                    gloss=request.gloss,
                    origin=request.origin,
                )
            except FormulaSyntaxError as exc:
                return FormulaReport(
                    valid=False,
                    formula=None,
                    errors=(Issue(code="syntax_error", message=str(exc), path="/text"),),
                    warnings=(),
                    atoms=AtomKinds(cardinality=False, fireability=False, deadlock=False),
                    uses_next=False,
                    text=request.text or "",
                )
        structure = build_structure(document=stored.document, net_id=request.net_id)
        return check_formula(formula=formula, structure=structure)

    def from_pattern(
        self, *, net_id: str, request: PatternRequest, formula_id: str
    ) -> FormulaReport:
        """Build the formula of a specification pattern and check it against the net.

        Raises:
            NotFoundError: if the net is unknown.
            InvalidRequestError: if the pattern lacks a parameter or a condition is temporal.
            FormulaSyntaxError: if a condition does not parse.
        """
        formula = instantiate(request=request, formula_id=formula_id)
        return self.validate(request=FormulaValidationRequest(net_id=net_id, formula=formula))
