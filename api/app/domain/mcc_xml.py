"""Formula trees written as the contest's property XML, which several tools read natively.

The inverse of ``mcc_properties.parse_property_set``: the contest's format has only "less or
equal", so the other comparisons are expressed with it and a negation, without changing meaning.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .errors import InvalidRequestError
from .formula import (
    And,
    Compare,
    Constant,
    CtlUnary,
    Deadlock,
    Enabled,
    Expression,
    Formula,
    Implies,
    LtlUnary,
    LtlUntil,
    Not,
    Or,
    Term,
    TokenCount,
    Tokens,
    Truth,
)

TEMPORAL_ELEMENT = {"G": "globally", "F": "finally", "X": "next"}


def wrap(*, tag: str, inner: str) -> str:
    """Return ``inner`` inside a ``tag`` element."""
    return f"<{tag}>{inner}</{tag}>"


def term_xml(*, term: Term) -> str:
    """Write a term: a constant or a sum of tokens."""
    if isinstance(term, Constant):
        return wrap(tag="integer-constant", inner=str(term.value))
    places = "".join(wrap(tag="place", inner=escape(place)) for place in term.places)
    return wrap(tag="tokens-count", inner=places)


def less_or_equal(*, left: Term, right: Term) -> str:
    """Write ``left <= right``."""
    return wrap(tag="integer-le", inner=term_xml(term=left) + term_xml(term=right))


def comparison_xml(*, left: Term, cmp: str, right: Term) -> str:
    """Write a comparison with the contest's only primitive, ``<=``, and boolean connectives."""
    if cmp == "<=":
        return less_or_equal(left=left, right=right)
    if cmp == ">=":
        return less_or_equal(left=right, right=left)
    if cmp == "<":
        return wrap(tag="negation", inner=less_or_equal(left=right, right=left))
    if cmp == ">":
        return wrap(tag="negation", inner=less_or_equal(left=left, right=right))
    both = wrap(
        tag="conjunction",
        inner=less_or_equal(left=left, right=right) + less_or_equal(left=right, right=left),
    )
    return both if cmp == "==" else wrap(tag="negation", inner=both)


def expression_xml(*, expression: Expression) -> str:  # noqa: PLR0911 - one return per operator
    """Write an expression as the contest's formula elements."""
    if isinstance(expression, Tokens):
        return comparison_xml(
            left=TokenCount(places=(expression.place,)),
            cmp=expression.cmp,
            right=Constant(value=expression.value),
        )
    if isinstance(expression, Compare):
        return comparison_xml(left=expression.left, cmp=expression.cmp, right=expression.right)
    if isinstance(expression, Enabled):
        return wrap(
            tag="is-fireable",
            inner=wrap(tag="transition", inner=escape(expression.transition)),
        )
    if isinstance(expression, Deadlock):
        return "<deadlock/>"
    if isinstance(expression, Truth):
        return "<true/>" if expression.value else "<false/>"
    if isinstance(expression, Not):
        return wrap(tag="negation", inner=expression_xml(expression=expression.arg))
    if isinstance(expression, And | Or):
        tag = "conjunction" if isinstance(expression, And) else "disjunction"
        return wrap(
            tag=tag, inner="".join(expression_xml(expression=arg) for arg in expression.args)
        )
    if isinstance(expression, Implies):
        return wrap(
            tag="disjunction",
            inner=wrap(tag="negation", inner=expression_xml(expression=expression.left))
            + expression_xml(expression=expression.right),
        )
    if isinstance(expression, LtlUnary):
        return wrap(
            tag=TEMPORAL_ELEMENT[expression.op], inner=expression_xml(expression=expression.arg)
        )
    if isinstance(expression, LtlUntil):
        return until_xml(left=expression.left, right=expression.right)
    if isinstance(expression, CtlUnary):
        return wrap(
            tag="all-paths" if expression.op.startswith("A") else "exists-path",
            inner=wrap(
                tag=TEMPORAL_ELEMENT[expression.op[1]],
                inner=expression_xml(expression=expression.arg),
            ),
        )
    return wrap(
        tag="all-paths" if expression.op == "AU" else "exists-path",
        inner=until_xml(left=expression.left, right=expression.right),
    )


def until_xml(*, left: Expression, right: Expression) -> str:
    """Write an until: the condition that must hold before, and the one that is reached."""
    return wrap(
        tag="until",
        inner=wrap(tag="before", inner=expression_xml(expression=left))
        + wrap(tag="reach", inner=expression_xml(expression=right)),
    )


def formula_xml(*, formula: Formula) -> str:
    """Write the ``formula`` element of one property.

    A ``state`` formula is the reachability of a marking that satisfies it; an LTL formula holds
    on all paths, as in the contest.
    """
    if formula.logic == "state":
        body = wrap(
            tag="exists-path",
            inner=wrap(tag="finally", inner=expression_xml(expression=formula.ast)),
        )
    elif formula.logic == "ltl":
        body = wrap(tag="all-paths", inner=expression_xml(expression=formula.ast))
    else:
        body = expression_xml(expression=formula.ast)
    return wrap(tag="formula", inner=body)


def render_property_set(*, formulas: tuple[Formula, ...]) -> str:
    """Write formulas as a contest ``property-set`` document, one property per formula.

    Raises:
        InvalidRequestError: if there is no formula (an empty property set is not a query).
    """
    if not formulas:
        raise InvalidRequestError("Nothing to write: no formula")
    properties = "".join(
        wrap(
            tag="property",
            inner=wrap(tag="id", inner=escape(formula.id))
            + wrap(tag="description", inner=escape(formula.gloss))
            + formula_xml(formula=formula),
        )
        for formula in formulas
    )
    return (
        '<?xml version="1.0"?>\n<property-set xmlns="http://mcc.lip6.fr/">'
        + properties
        + "</property-set>\n"
    )
