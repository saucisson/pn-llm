"""Check a formula against a net and report what it needs: errors, warnings and atom classes.

Errors make a formula unusable (unknown ids, operators that do not belong to its logic).
Warnings are things an engine adapter or the caller must know: the neXt operator, which limits
the reductions that may be applied (domain rule 3), and mixed atom classes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from .formula import (
    Compare,
    CtlUnary,
    CtlUntil,
    Deadlock,
    Enabled,
    Expression,
    Formula,
    Logic,
    LtlUnary,
    LtlUntil,
    Origin,
    TokenCount,
    Tokens,
    subexpressions,
)
from .formula_text import render_text
from .inspection import closest_ids
from .models import DomainModel
from .net_structure import NetStructure

LTL_OPERATORS = frozenset({"G", "F", "X", "U"})
CTL_OPERATORS = frozenset({"AG", "AF", "AX", "EG", "EF", "EX", "AU", "EU"})


class Issue(DomainModel):
    """An error or a warning, with a JSON pointer to the part of the formula it is about."""

    code: str
    message: str
    path: str


class AtomKinds(DomainModel):
    """Which classes of atom a formula uses; the MCC keeps two classes apart."""

    cardinality: bool
    fireability: bool
    deadlock: bool


class FormulaReport(DomainModel):
    """Outcome of checking a formula against a net."""

    valid: bool
    formula: Formula | None
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]
    atoms: AtomKinds
    uses_next: bool
    text: str


class Citation(DomainModel):
    """An element id cited by an atom, the kind of element expected, and where it is cited."""

    element_id: str
    wanted: Literal["place", "transition"]
    path: str


def citations(*, node: Expression, path: str) -> tuple[Citation, ...]:
    """List the ids an atom cites; other nodes cite nothing."""
    if isinstance(node, Tokens):
        return (Citation(element_id=node.place, wanted="place", path=f"{path}/place"),)
    if isinstance(node, Enabled):
        return (
            Citation(element_id=node.transition, wanted="transition", path=f"{path}/transition"),
        )
    if isinstance(node, Compare):
        return tuple(
            Citation(element_id=place, wanted="place", path=f"{path}/{side}/places/{index}")
            for side, term in (("left", node.left), ("right", node.right))
            if isinstance(term, TokenCount)
            for index, place in enumerate(term.places)
        )
    return ()


def operator_issue(*, logic: Logic, node: Expression, path: str) -> Issue | None:
    """Return the error for a temporal operator that does not belong to ``logic``, if any."""
    if not isinstance(node, LtlUnary | LtlUntil | CtlUnary | CtlUntil):
        return None
    operator = node.op
    if logic == "state":
        return Issue(
            code="temporal_operator_in_state_formula",
            message=f"operator {operator} is not allowed in a state formula",
            path=path,
        )
    if logic == "ltl" and operator in CTL_OPERATORS:
        return Issue(
            code="ctl_operator_in_ltl",
            message=f"operator {operator} is CTL, the formula is LTL",
            path=path,
        )
    if logic == "ctl" and operator in LTL_OPERATORS:
        return Issue(
            code="ltl_operator_in_ctl",
            message=f"operator {operator} is LTL, the formula is CTL",
            path=path,
        )
    return None


def check_formula(*, formula: Formula, structure: NetStructure) -> FormulaReport:
    """Check ids and operators of ``formula`` against ``structure``."""
    kinds = {node.id: node.kind for node in (*structure.places, *structure.transitions)}
    ids = tuple(kinds)
    errors: list[Issue] = []
    cardinality = fireability = deadlock = uses_next = False

    for located in subexpressions(expression=formula.ast, path="/ast"):
        node, path = located.expression, located.path
        cardinality = cardinality or isinstance(node, Tokens | Compare)
        fireability = fireability or isinstance(node, Enabled)
        deadlock = deadlock or isinstance(node, Deadlock)
        uses_next = uses_next or (
            isinstance(node, LtlUnary | CtlUnary) and node.op in {"X", "AX", "EX"}
        )
        issue = operator_issue(logic=formula.logic, node=node, path=path)
        if issue is not None:
            errors.append(issue)
        for citation in citations(node=node, path=path):
            actual = kinds.get(citation.element_id)
            if actual == citation.wanted:
                continue
            if actual is None:
                close = closest_ids(element_id=citation.element_id, ids=ids)
                hint = f"; closest ids: {', '.join(close)}" if close else ""
                errors.append(
                    Issue(
                        code=f"unknown_{citation.wanted}",
                        message=(
                            f"{citation.element_id!r} is not a {citation.wanted} of the net{hint}"
                        ),
                        path=citation.path,
                    )
                )
            else:
                errors.append(
                    Issue(
                        code=f"not_a_{citation.wanted}",
                        message=(
                            f"{citation.element_id!r} is a {actual}, "
                            f"a {citation.wanted} is expected here"
                        ),
                        path=citation.path,
                    )
                )

    warnings: list[Issue] = []
    if uses_next:
        warnings.append(
            Issue(
                code="uses_next",
                message=(
                    "The neXt operator makes the formula stutter-sensitive: only reductions that "
                    "preserve stuttering may be applied"
                ),
                path="/ast",
            )
        )
    if cardinality and fireability:
        warnings.append(
            Issue(
                code="mixed_atom_classes",
                message="Cardinality and fireability atoms are mixed: some engines take one class",
                path="/ast",
            )
        )
    return FormulaReport(
        valid=not errors,
        formula=formula,
        errors=tuple(errors),
        warnings=tuple(warnings),
        atoms=AtomKinds(cardinality=cardinality, fireability=fireability, deadlock=deadlock),
        uses_next=uses_next,
        text=render_text(expression=formula.ast),
    )


class FormulaValidationRequest(DomainModel):
    """Body of ``POST /v1/formulas/validate``: a net and either a formula tree or formula text."""

    net_id: str
    formula: Formula | None = None
    text: str | None = None
    # The following apply to ``text`` only: without ``logic`` it follows from the operators used.
    logic: Logic | None = None
    id: str = "f1"
    gloss: str = ""
    origin: Origin = "user"

    @model_validator(mode="after")
    def _exactly_one_of_formula_and_text(self) -> FormulaValidationRequest:
        """Reject a request that gives both a tree and text, or neither."""
        if (self.formula is None) == (self.text is None):
            message = "give exactly one of formula and text"
            raise ValueError(message)
        return self
