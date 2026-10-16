"""Properties of a colored net, written for its unfolding.

A property of a colored net cites its places and transitions. On the unfolded net, a colored place
is the set of its unfolded places (its token count is their sum) and a colored transition is
fireable when one of its unfolded transitions is. The lineage of the unfolded net holds that
mapping, so a property written about the colored net is translated for the engine without the user
or the model having to know the names of the unfolded elements (docs/colored-nets.md).
"""

from __future__ import annotations

from .formula import (
    Compare,
    Constant,
    Enabled,
    Expression,
    Formula,
    Or,
    TokenCount,
    Tokens,
    Truth,
    rewrite_atoms,
)
from .operations import Lineage


def translate_expression(*, expression: Expression, lineage: Lineage) -> Expression:
    """Replace the colored places and transitions an expression cites by their unfolded ones.

    A citation that is not a colored element of the parent stays as it is: it is checked against
    the unfolded net, which can reject it.
    """
    places: dict[str, list[str]] = {}
    for item in lineage.places:
        places.setdefault(item.original, []).append(item.unfolded)
    transitions: dict[str, list[str]] = {}
    for expansion in lineage.expansions:
        if len(expansion.original) == 1:
            transitions.setdefault(expansion.original[0], []).append(expansion.transition)

    def spread(*, ids: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(u for i in ids for u in places.get(i, [i]))

    def translate(*, atom: Tokens | Compare | Enabled) -> Expression:
        if isinstance(atom, Tokens):
            unfolded = spread(ids=(atom.place,))
            if len(unfolded) == 1:
                return atom.model_copy(update={"place": unfolded[0]})
            return Compare(
                left=TokenCount(places=unfolded),
                cmp=atom.cmp,
                right=Constant(value=atom.value),
            )
        if isinstance(atom, Enabled):
            unfolded = tuple(transitions.get(atom.transition, [atom.transition]))
            if not unfolded:
                return Truth(value=False)
            if len(unfolded) == 1:
                return atom.model_copy(update={"transition": unfolded[0]})
            return Or(args=tuple(Enabled(transition=t) for t in unfolded))
        sides = {
            side: TokenCount(places=spread(ids=term.places))
            if isinstance(term, TokenCount)
            else term
            for side, term in (("left", atom.left), ("right", atom.right))
        }
        return atom.model_copy(update=sides)

    return rewrite_atoms(expression=expression, rewrite=translate)


def translate_formula(*, formula: Formula, lineage: Lineage) -> Formula:
    """Return the formula written for the unfolded net; id, logic, gloss and origin are kept."""
    return formula.model_copy(
        update={"ast": translate_expression(expression=formula.ast, lineage=lineage)}
    )
