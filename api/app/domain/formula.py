"""Structured formulas: syntax trees whose atoms cite places and transitions by id (ADR 0013).

The LLM writes trees (or text that the platform parses into trees); it never writes the syntax of
an engine. Each engine adapter renders its own syntax from the tree. See docs/json-contract.md.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .base import DomainModel

Comparison = Literal["<", "<=", "==", "!=", ">=", ">"]
Logic = Literal["ltl", "ctl", "state"]
Origin = Literal["user", "llm", "template", "mcc"]


class TokenCount(DomainModel):
    """A term: the sum of the tokens held by some places."""

    kind: Literal["tokens"] = "tokens"
    places: tuple[str, ...] = Field(min_length=1)


class Constant(DomainModel):
    """A term: a non-negative integer."""

    kind: Literal["const"] = "const"
    value: int = Field(ge=0)


Term = Annotated[TokenCount | Constant, Field(discriminator="kind")]


class Tokens(DomainModel):
    """Cardinality atom on one place: its tokens compared with a constant."""

    op: Literal["tokens"] = "tokens"
    place: str
    cmp: Comparison
    value: int = Field(ge=0)


class Compare(DomainModel):
    """Cardinality atom on general terms, such as ``p1 + p2 <= p3``."""

    op: Literal["compare"] = "compare"
    left: Term
    cmp: Comparison
    right: Term


class Enabled(DomainModel):
    """Fireability atom: the transition can fire."""

    op: Literal["enabled"] = "enabled"
    transition: str


class Deadlock(DomainModel):
    """Atom: no transition can fire."""

    op: Literal["deadlock"] = "deadlock"


class Truth(DomainModel):
    """The constants true and false."""

    op: Literal["const"] = "const"
    value: bool


class Not(DomainModel):
    """Negation."""

    op: Literal["not"] = "not"
    arg: Expression


class And(DomainModel):
    """Conjunction of at least two operands."""

    op: Literal["and"] = "and"
    args: tuple[Expression, ...] = Field(min_length=2)


class Or(DomainModel):
    """Disjunction of at least two operands."""

    op: Literal["or"] = "or"
    args: tuple[Expression, ...] = Field(min_length=2)


class Implies(DomainModel):
    """Implication."""

    op: Literal["implies"] = "implies"
    left: Expression
    right: Expression


class LtlUnary(DomainModel):
    """LTL operators with one operand: always, eventually, next."""

    op: Literal["G", "F", "X"]
    arg: Expression


class LtlUntil(DomainModel):
    """LTL strong until."""

    op: Literal["U"] = "U"
    left: Expression
    right: Expression


class CtlUnary(DomainModel):
    """CTL operators with one operand: a path quantifier and a temporal operator."""

    op: Literal["AG", "AF", "AX", "EG", "EF", "EX"]
    arg: Expression


class CtlUntil(DomainModel):
    """CTL until under a path quantifier."""

    op: Literal["AU", "EU"]
    left: Expression
    right: Expression


Expression = Annotated[
    Tokens
    | Compare
    | Enabled
    | Deadlock
    | Truth
    | Not
    | And
    | Or
    | Implies
    | LtlUnary
    | LtlUntil
    | CtlUnary
    | CtlUntil,
    Field(discriminator="op"),
]

for _model in (Not, And, Or, Implies, LtlUnary, LtlUntil, CtlUnary, CtlUntil):
    _model.model_rebuild()


class Formula(DomainModel):
    """A property to check, with the plain-language gloss its proposer gave and its origin.

    ``logic`` is ``ltl`` (checked on every run), ``ctl`` (branching time) or ``state`` (a
    condition on one marking, checked for reachability: some reachable marking satisfies it).
    """

    id: str = Field(min_length=1)
    logic: Logic
    ast: Expression
    gloss: str = ""
    origin: Origin = "user"


class Located(DomainModel):
    """A sub-expression and its JSON pointer."""

    path: str
    expression: Expression


def subexpressions(*, expression: Expression, path: str) -> tuple[Located, ...]:
    """List ``expression`` and everything below it, parents first, each with its JSON pointer.

    ``path`` is the pointer of ``expression`` itself.
    """
    found: list[Located] = []
    pending = [Located(path=path, expression=expression)]
    while pending:
        current = pending.pop(0)
        found.append(current)
        node = current.expression
        if isinstance(node, Not | LtlUnary | CtlUnary):
            pending.append(Located(path=f"{current.path}/arg", expression=node.arg))
        elif isinstance(node, And | Or):
            pending.extend(
                Located(path=f"{current.path}/args/{index}", expression=arg)
                for index, arg in enumerate(node.args)
            )
        elif isinstance(node, Implies | LtlUntil | CtlUntil):
            pending.append(Located(path=f"{current.path}/left", expression=node.left))
            pending.append(Located(path=f"{current.path}/right", expression=node.right))
    return tuple(found)
