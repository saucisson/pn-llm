"""Contest properties: the formula XML of each examination, read into formula trees."""

from __future__ import annotations

from typing import Literal
from xml.etree.ElementTree import Element, ParseError  # types only: parsing uses defusedxml

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET  # hardened against DTDs and entity expansion

from .errors import InvalidRequestError
from .formula import (
    And,
    Compare,
    Constant,
    CtlUnary,
    CtlUntil,
    Enabled,
    Expression,
    Formula,
    LtlUnary,
    LtlUntil,
    Not,
    Or,
    Term,
    TokenCount,
    Tokens,
)
from .models import DomainModel

Examination = Literal[
    "ReachabilityCardinality",
    "ReachabilityFireability",
    "CTLCardinality",
    "CTLFireability",
    "LTLCardinality",
    "LTLFireability",
    "UpperBounds",
]
EXAMINATIONS: tuple[Examination, ...] = (
    "ReachabilityCardinality",
    "ReachabilityFireability",
    "CTLCardinality",
    "CTLFireability",
    "LTLCardinality",
    "LTLFireability",
    "UpperBounds",
)
NAMESPACE = "{http://mcc.lip6.fr/}"
TEMPORAL = {"globally": "G", "finally": "F", "next": "X"}


class BoundQuery(DomainModel):
    """An upper-bound question: the greatest total of tokens the places can hold together."""

    id: str
    places: tuple[str, ...]
    gloss: str = ""
    origin: Literal["mcc"] = "mcc"


class MccProperties(DomainModel):
    """The properties the contest asks about one instance, for one examination."""

    examination: Examination
    formulas: tuple[Formula, ...] = ()
    bounds: tuple[BoundQuery, ...] = ()


def local(*, element: Element) -> str:
    """Return a tag without its namespace."""
    return element.tag.removeprefix(NAMESPACE)


def read_term(*, element: Element) -> Term:
    """Read ``integer-constant`` or ``tokens-count`` (the sum over its places)."""
    name = local(element=element)
    if name == "integer-constant":
        return Constant(value=int((element.text or "").strip()))
    if name == "tokens-count":
        return TokenCount(places=tuple((child.text or "").strip() for child in element))
    raise InvalidRequestError(f"unsupported term <{name}>")


def read_expression(  # noqa: PLR0911 - one return per element kind of the contest's format
    *, element: Element, temporal: Literal["none", "ltl", "ctl"]
) -> Expression:
    """Read a formula element into the tree.

    ``temporal`` says which temporal operators are allowed: none (a condition on a marking),
    LTL operators alone, or CTL operators, which the contest writes as a path quantifier wrapped
    around a temporal operator.

    Raises:
        InvalidRequestError: for an element the contest does not define or a misplaced operator;
            nothing is skipped silently, because dropping a subformula would change its meaning.
    """
    name = local(element=element)
    children = tuple(element)
    if name == "integer-le":
        left = read_term(element=children[0])
        right = read_term(element=children[1])
        if isinstance(left, TokenCount) and len(left.places) == 1 and isinstance(right, Constant):
            return Tokens(place=left.places[0], cmp="<=", value=right.value)
        if isinstance(right, TokenCount) and len(right.places) == 1 and isinstance(left, Constant):
            return Tokens(place=right.places[0], cmp=">=", value=left.value)
        return Compare(left=left, cmp="<=", right=right)
    if name == "is-fireable":
        enabled = tuple(Enabled(transition=(child.text or "").strip()) for child in children)
        return enabled[0] if len(enabled) == 1 else Or(args=enabled)
    if name in {"conjunction", "disjunction"}:
        operands = tuple(read_expression(element=child, temporal=temporal) for child in children)
        if len(operands) == 1:
            return operands[0]
        return And(args=operands) if name == "conjunction" else Or(args=operands)
    if name == "negation":
        return Not(arg=read_expression(element=children[0], temporal=temporal))
    if temporal == "ltl" and name in TEMPORAL:
        return LtlUnary(
            op=TEMPORAL[name],
            arg=read_expression(element=children[0], temporal=temporal),
        )
    if temporal == "ltl" and name == "until":
        return LtlUntil(
            left=read_expression(element=children[0][0], temporal=temporal),
            right=read_expression(element=children[1][0], temporal=temporal),
        )
    if temporal == "ctl" and name in {"all-paths", "exists-path"}:
        quantifier = "A" if name == "all-paths" else "E"
        inner = children[0]
        inner_name = local(element=inner)
        if inner_name == "until":
            return CtlUntil(
                op=f"{quantifier}U",
                left=read_expression(element=inner[0][0], temporal=temporal),
                right=read_expression(element=inner[1][0], temporal=temporal),
            )
        if inner_name in TEMPORAL:
            return CtlUnary(
                op=f"{quantifier}{TEMPORAL[inner_name]}",
                arg=read_expression(element=inner[0], temporal=temporal),
            )
    raise InvalidRequestError(f"unsupported or misplaced element <{name}>")


def read_formula(
    *, examination: Examination, element: Element, property_id: str, gloss: str
) -> Formula:
    """Read the ``formula`` element of one property of a Boolean examination."""
    top = element[0]
    top_name = local(element=top)
    if examination.startswith("LTL"):
        if top_name != "all-paths":
            raise InvalidRequestError(f"{property_id}: an LTL property starts with all-paths")
        return Formula(
            id=property_id,
            logic="ltl",
            ast=read_expression(element=top[0], temporal="ltl"),
            gloss=gloss,
            origin="mcc",
        )
    if examination.startswith("CTL"):
        return Formula(
            id=property_id,
            logic="ctl",
            ast=read_expression(element=top, temporal="ctl"),
            gloss=gloss,
            origin="mcc",
        )
    # Reachability: "some reachable marking satisfies the condition" is the state logic; any other
    # shape (such as an invariant) keeps its temporal operator rather than being rewritten.
    reaches = top_name == "exists-path" and local(element=top[0]) == "finally"
    return Formula(
        id=property_id,
        logic="state" if reaches else "ctl",
        ast=read_expression(
            element=top[0][0] if reaches else top,
            temporal="none" if reaches else "ctl",
        ),
        gloss=gloss,
        origin="mcc",
    )


def parse_property_set(*, examination: Examination, xml: bytes) -> MccProperties:
    """Read a ``property-set`` document of one examination.

    Raises:
        InvalidRequestError: if the document is not well-formed or uses an element not handled.
    """
    try:
        root = SafeET.fromstring(xml)
    except (ParseError, DefusedXmlException) as exc:
        raise InvalidRequestError(f"invalid property file: {exc}") from exc
    formulas: list[Formula] = []
    bounds: list[BoundQuery] = []
    for item in root:
        property_id = (item.findtext(f"{NAMESPACE}id") or "").strip()
        gloss = (item.findtext(f"{NAMESPACE}description") or "").strip()
        formula = item.find(f"{NAMESPACE}formula")
        if formula is None or not property_id or len(formula) == 0:
            raise InvalidRequestError("a property without id or formula")
        if examination == "UpperBounds":
            bound = formula[0]
            if local(element=bound) != "place-bound":
                raise InvalidRequestError(f"{property_id}: expected <place-bound>")
            places = tuple((place.text or "").strip() for place in bound)
            bounds.append(BoundQuery(id=property_id, places=places, gloss=gloss))
        else:
            formulas.append(
                read_formula(
                    examination=examination, element=formula, property_id=property_id, gloss=gloss
                )
            )
    return MccProperties(examination=examination, formulas=tuple(formulas), bounds=tuple(bounds))
