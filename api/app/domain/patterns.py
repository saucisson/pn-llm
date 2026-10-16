"""Specification patterns: the usual questions about a system, as formulas built without guessing.

The LLM picks a pattern and gives its parameters (conditions on markings, written in the text
syntax); the formula is generated here, deterministically, so a common property does not depend on
the model writing the right temporal operators (docs/formula-syntax.md). Patterns follow Dwyer,
Avrunin and Corbett, "Patterns in property specifications for finite-state verification" (1999),
in their global scope.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .errors import InvalidRequestError
from .formula import (
    And,
    CtlUnary,
    CtlUntil,
    Expression,
    Formula,
    Implies,
    Logic,
    LtlUnary,
    LtlUntil,
    Not,
    Or,
    Tokens,
    subexpressions,
)
from .formula_text import parse_expression, render_text
from .models import DomainModel

Pattern = Literal[
    "absence",
    "universality",
    "existence",
    "bound",
    "response",
    "precedence",
    "exclusion",
    "recurrence",
]


class PatternInfo(DomainModel):
    """A pattern, what it means and which parameters it takes."""

    name: Pattern
    meaning: str
    parameters: tuple[str, ...]


PATTERNS: tuple[PatternInfo, ...] = (
    PatternInfo(name="absence", meaning="P never holds", parameters=("p",)),
    PatternInfo(name="universality", meaning="P holds in every state", parameters=("p",)),
    PatternInfo(
        name="existence",
        meaning="P can hold (CTL: some run reaches it; LTL: every run reaches it)",
        parameters=("p",),
    ),
    PatternInfo(
        name="bound",
        meaning="the place named by P never holds more than K tokens",
        parameters=("p", "k"),
    ),
    PatternInfo(
        name="response", meaning="whenever P holds, Q holds then or later", parameters=("p", "q")
    ),
    PatternInfo(
        name="precedence", meaning="P never holds before Q has held", parameters=("p", "q")
    ),
    PatternInfo(name="exclusion", meaning="P and Q never hold together", parameters=("p", "q")),
    PatternInfo(name="recurrence", meaning="P holds again and again", parameters=("p",)),
)


class PatternRequest(DomainModel):
    """What the model gives to build a formula from a pattern."""

    pattern: Pattern
    logic: Literal["ctl", "ltl"] = "ctl"
    p: str = Field(min_length=1, description="Condition on a marking, in the text syntax")
    q: str | None = Field(
        default=None, description="Second condition (response, precedence, exclusion)"
    )
    k: int | None = Field(default=None, ge=0, description="Token bound (bound)")


def always(*, logic: Logic, body: Expression) -> Expression:
    """Write "in every state" in the chosen logic."""
    return CtlUnary(op="AG", arg=body) if logic == "ctl" else LtlUnary(op="G", arg=body)


def eventually_on_all_paths(*, logic: Logic, body: Expression) -> Expression:
    """Write "on every path, sooner or later" in the chosen logic."""
    return CtlUnary(op="AF", arg=body) if logic == "ctl" else LtlUnary(op="F", arg=body)


def instantiate(*, request: PatternRequest, formula_id: str) -> Formula:
    """Build the formula of a pattern with its parameters.

    Raises:
        InvalidRequestError: if a parameter the pattern needs is missing, or a condition is not a
            condition on one marking (it may not use temporal operators).
        FormulaSyntaxError: if a condition does not parse.
    """
    logic = request.logic
    needs = next(info.parameters for info in PATTERNS if info.name == request.pattern)
    first = parse_expression(text=request.p)
    second = None if request.q is None else parse_expression(text=request.q)
    if "q" in needs and second is None:
        raise InvalidRequestError(f"The pattern {request.pattern} needs the parameter q")
    if "k" in needs and request.k is None:
        raise InvalidRequestError(f"The pattern {request.pattern} needs the parameter k")
    for name, condition in (("p", first), ("q", second)):
        if condition is not None and any(
            isinstance(part.expression, CtlUnary | CtlUntil | LtlUnary | LtlUntil)
            for part in subexpressions(expression=condition, path="")
        ):
            raise InvalidRequestError(f"The condition {name} must not use temporal operators")
    p = first
    # Only the patterns that take a second condition read it; for the others it stands for p.
    q: Expression = second if second is not None else first
    body: Expression
    gloss: str
    if request.pattern == "absence":
        body, gloss = (
            always(logic=logic, body=Not(arg=p)),
            f"{render_text(expression=p)} never holds",
        )
    elif request.pattern == "universality":
        body, gloss = (
            always(logic=logic, body=p),
            f"{render_text(expression=p)} holds in every state",
        )
    elif request.pattern == "existence":
        body = CtlUnary(op="EF", arg=p) if logic == "ctl" else LtlUnary(op="F", arg=p)
        gloss = (
            f"{render_text(expression=p)} can hold"
            if logic == "ctl"
            else (f"{render_text(expression=p)} holds sooner or later on every run")
        )
    elif request.pattern == "bound":
        if not isinstance(p, Tokens):
            raise InvalidRequestError(
                "The bound pattern takes a place: p must be a comparison on one place"
            )
        body = always(logic=logic, body=Tokens(place=p.place, cmp="<=", value=request.k or 0))
        gloss = f"{p.place} never holds more than {request.k} tokens"
    elif request.pattern == "response":
        body = always(
            logic=logic, body=Implies(left=p, right=eventually_on_all_paths(logic=logic, body=q))
        )
        gloss = (
            f"whenever {render_text(expression=p)} holds, "
            f"{render_text(expression=q)} holds then or later"
        )
    elif request.pattern == "precedence":
        # P is never true unless Q has held before (or at) that moment: weak until, written with
        # the operators of the logic.
        if logic == "ctl":
            body = Not(arg=CtlUntil(op="EU", left=Not(arg=q), right=And(args=(p, Not(arg=q)))))
        else:
            body = Or(
                args=(
                    LtlUntil(left=Not(arg=p), right=q),
                    LtlUnary(op="G", arg=Not(arg=p)),
                )
            )
        gloss = (
            f"{render_text(expression=p)} never holds before {render_text(expression=q)} has held"
        )
    elif request.pattern == "exclusion":
        body = always(logic=logic, body=Not(arg=And(args=(p, q))))
        gloss = f"{render_text(expression=p)} and {render_text(expression=q)} never hold together"
    else:
        body = (
            CtlUnary(op="AG", arg=CtlUnary(op="AF", arg=p))
            if logic == "ctl"
            else LtlUnary(op="G", arg=LtlUnary(op="F", arg=p))
        )
        gloss = f"{render_text(expression=p)} holds again and again"
    return Formula(id=formula_id, logic=logic, ast=body, gloss=gloss, origin="template")
