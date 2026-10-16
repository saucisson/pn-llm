"""Colored nets, typed: arc inscriptions, markings and guards read from their XML trees."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .colored import UnsupportedColoredError, attribute, children, local
from .models import DomainModel
from .net_document import Annotation, XmlNode


class VariableTerm(DomainModel):
    """A variable, by id."""

    kind: Literal["variable"] = "variable"
    variable: str


class ConstantTerm(DomainModel):
    """A named value of an enumeration, by id."""

    kind: Literal["constant"] = "constant"
    operator: str


class DotTerm(DomainModel):
    """The only value of the dot sort."""

    kind: Literal["dot"] = "dot"


class NumberTerm(DomainModel):
    """A natural number, as a multiplicity."""

    kind: Literal["number"] = "number"
    value: int


class AllTerm(DomainModel):
    """Every value of a sort."""

    kind: Literal["all"] = "all"
    sort: str


class TupleTerm(DomainModel):
    """A value of a product sort."""

    kind: Literal["tuple"] = "tuple"
    items: tuple[Term, ...]


class SuccessorTerm(DomainModel):
    """The next value of a sort."""

    kind: Literal["successor"] = "successor"
    argument: Term


class PredecessorTerm(DomainModel):
    """The previous value of a sort."""

    kind: Literal["predecessor"] = "predecessor"
    argument: Term


class NumberOfTerm(DomainModel):
    """``n'x``: ``n`` copies of the value ``x``."""

    kind: Literal["numberof"] = "numberof"
    count: int
    item: Term


class AddTerm(DomainModel):
    """The sum of multisets."""

    kind: Literal["add"] = "add"
    arguments: tuple[Term, ...]


class SubtractTerm(DomainModel):
    """The difference of two multisets."""

    kind: Literal["subtract"] = "subtract"
    left: Term
    right: Term


Term = Annotated[
    VariableTerm
    | ConstantTerm
    | DotTerm
    | NumberTerm
    | AllTerm
    | TupleTerm
    | SuccessorTerm
    | PredecessorTerm
    | NumberOfTerm
    | AddTerm
    | SubtractTerm,
    Field(discriminator="kind"),
]

COMPARISONS = {
    "equality": "==",
    "inequality": "!=",
    "lessthan": "<",
    "lessthanorequal": "<=",
    "greaterthan": ">",
    "greaterthanorequal": ">=",
}


class Comparison(DomainModel):
    """A comparison of two terms in a guard."""

    kind: Literal["comparison"] = "comparison"
    operator: Literal["==", "!=", "<", "<=", ">", ">="]
    left: Term
    right: Term


class Junction(DomainModel):
    """``and`` / ``or`` of guards."""

    kind: Literal["junction"] = "junction"
    operator: Literal["and", "or"]
    arguments: tuple[Guard, ...]


class Negation(DomainModel):
    """``not`` of a guard."""

    kind: Literal["not"] = "not"
    argument: Guard


Guard = Annotated[Comparison | Junction | Negation, Field(discriminator="kind")]


def operands(*, node: XmlNode) -> tuple[XmlNode, ...]:
    """Return the term inside each ``subterm`` child of a node."""
    found = []
    for child in children(node=node):
        if local(name=child.name) != "subterm":
            raise UnsupportedColoredError(
                f"<{local(name=node.name)}> holds <{local(name=child.name)}>, not a subterm"
            )
        (inner,) = children(node=child)
        while local(name=inner.name) == "subterm":  # some models wrap a term twice
            (inner,) = children(node=inner)
        found.append(inner)
    return tuple(found)


def read_term(*, node: XmlNode) -> Term:  # noqa: PLR0911 - one return per kind of term
    """Read a term.

    Raises:
        UnsupportedColoredError: for a construct outside the supported vocabulary.
    """
    kind = local(name=node.name)
    if kind == "variable":
        return VariableTerm(variable=attribute(node=node, name="refvariable"))
    if kind == "useroperator":
        return ConstantTerm(operator=attribute(node=node, name="declaration"))
    if kind == "dotconstant":
        return DotTerm()
    if kind == "numberconstant":
        return NumberTerm(value=int(attribute(node=node, name="value")))
    if kind == "all":
        (sort,) = children(node=node)
        return AllTerm(sort=attribute(node=sort, name="declaration"))
    if kind == "tuple":
        return TupleTerm(items=tuple(read_term(node=n) for n in operands(node=node)))
    if kind in {"successor", "predecessor"}:
        (inner,) = operands(node=node)
        return (SuccessorTerm if kind == "successor" else PredecessorTerm)(
            argument=read_term(node=inner)
        )
    if kind == "numberof":
        count, item = operands(node=node)
        counted = read_term(node=count)
        if not isinstance(counted, NumberTerm):
            raise UnsupportedColoredError("A multiplicity must be a number")
        return NumberOfTerm(count=counted.value, item=read_term(node=item))
    if kind == "add":
        return AddTerm(arguments=tuple(read_term(node=n) for n in operands(node=node)))
    if kind == "subtract":
        left, right = operands(node=node)
        return SubtractTerm(left=read_term(node=left), right=read_term(node=right))
    raise UnsupportedColoredError(f"The term <{kind}> is not supported")


def read_guard(*, node: XmlNode) -> Guard:
    """Read a guard.

    Raises:
        UnsupportedColoredError: for a construct outside the supported vocabulary.
    """
    kind = local(name=node.name)
    if kind in COMPARISONS:
        left, right = operands(node=node)
        return Comparison(
            operator=COMPARISONS[kind],
            left=read_term(node=left),
            right=read_term(node=right),
        )
    if kind in {"and", "or"}:
        return Junction(
            operator=kind,
            arguments=tuple(read_guard(node=n) for n in operands(node=node)),
        )
    if kind == "not":
        (inner,) = operands(node=node)
        return Negation(argument=read_guard(node=inner))
    raise UnsupportedColoredError(f"The guard <{kind}> is not supported")


def read_annotation_term(*, annotation: Annotation | None) -> Term | None:
    """Read the term of an inscription or marking annotation, or None if it has none."""
    if annotation is None or annotation.structure is None:
        return None
    (inner,) = children(node=annotation.structure)
    return read_term(node=inner)


def read_annotation_guard(*, annotation: Annotation | None) -> Guard | None:
    """Read the guard of a transition's condition annotation, or None if it has none."""
    if annotation is None or annotation.structure is None:
        return None
    (inner,) = children(node=annotation.structure)
    return read_guard(node=inner)


def variables_of_term(*, term: Term) -> frozenset[str]:  # noqa: PLR0911 - one return per kind of term
    """Return the ids of the variables a term uses."""
    if isinstance(term, VariableTerm):
        return frozenset({term.variable})
    if isinstance(term, TupleTerm):
        return frozenset().union(*(variables_of_term(term=t) for t in term.items))
    if isinstance(term, SuccessorTerm | PredecessorTerm):
        return variables_of_term(term=term.argument)
    if isinstance(term, NumberOfTerm):
        return variables_of_term(term=term.item)
    if isinstance(term, AddTerm):
        return frozenset().union(*(variables_of_term(term=t) for t in term.arguments))
    if isinstance(term, SubtractTerm):
        return variables_of_term(term=term.left) | variables_of_term(term=term.right)
    return frozenset()


def variables_of_guard(*, guard: Guard) -> frozenset[str]:
    """Return the ids of the variables a guard uses."""
    if isinstance(guard, Comparison):
        return variables_of_term(term=guard.left) | variables_of_term(term=guard.right)
    if isinstance(guard, Junction):
        return frozenset().union(*(variables_of_guard(guard=g) for g in guard.arguments))
    return variables_of_guard(guard=guard.argument)


for _model in (
    TupleTerm,
    SuccessorTerm,
    PredecessorTerm,
    NumberOfTerm,
    AddTerm,
    SubtractTerm,
    Comparison,
    Junction,
    Negation,
):
    _model.model_rebuild()
