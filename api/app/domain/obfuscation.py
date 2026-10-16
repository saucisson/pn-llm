"""Condition N: the same net with its names replaced, and the way back for judging.

The names of places and transitions are the semantic signal a language model reads. Condition N
measures how much it relies on them by giving it a net where they say nothing (``p1``, ``t1``,
...). The renaming is deterministic (ids in sorted order) and kept as a list, so the properties the
model writes about ``p3`` are mapped back to the original places before engines judge them.
Only P/T nets are renamed: the declarations of a colored net would need renaming too.
"""

from __future__ import annotations

from typing import Literal

from .errors import InvalidRequestError
from .formula import (
    And,
    Compare,
    CtlUnary,
    CtlUntil,
    Enabled,
    Expression,
    Formula,
    Implies,
    LtlUnary,
    LtlUntil,
    Not,
    Or,
    TokenCount,
    Tokens,
)
from .models import DomainModel
from .net_document import (
    Annotation,
    Container,
    NetDocument,
)

CLEARED: dict[str, object] = {
    "tool_specific": (),
    "extensions": (),
    "extra_attributes": (),
    "graphics": None,
}


class Renaming(DomainModel):
    """One element and the name the model sees for it."""

    kind: Literal["place", "transition"]
    original: str
    obfuscated: str


class ObfuscatedNet(DomainModel):
    """The net the model sees, and the renamings that map its answers back."""

    document: NetDocument
    renamings: tuple[Renaming, ...]


def obfuscate_names(*, document: NetDocument) -> ObfuscatedNet:
    """Rename every place, transition, arc and page; drop every name and tool-specific datum.

    Raises:
        InvalidRequestError: if the net is not a P/T net.
    """
    if document.kind != "pt":
        raise InvalidRequestError("Names can be obfuscated on P/T nets only")
    located_all = document.located_containers()
    containers = [located.container for located in located_all]
    place_ids = {p.id for c in containers for p in c.places}
    place_ids |= {r.id for c in containers for r in c.ref_places}
    transition_ids = {t.id for c in containers for t in c.transitions}
    transition_ids |= {r.id for c in containers for r in c.ref_transitions}
    places = {original: f"p{i}" for i, original in enumerate(sorted(place_ids), start=1)}
    transitions = {original: f"t{i}" for i, original in enumerate(sorted(transition_ids), start=1)}
    both = {**places, **transitions}
    arcs = {a: f"a{i}" for i, a in enumerate(sorted(a.id for c in containers for a in c.arcs), 1)}
    page_ids = sorted(item.page_id for item in located_all if item.page_id is not None)
    pages = {p: f"page{i}" for i, p in enumerate(page_ids, start=1)}

    def rewrite[C: Container](*, container: C) -> C:
        """Rename what is in a container; the container keeps its own id (see ``pages``)."""
        return container.model_copy(
            update={
                **CLEARED,
                "name": None,
                "declaration": None,
                "pages": tuple(
                    rewrite(container=page).model_copy(update={"id": pages[page.id]})
                    for page in sorted(container.pages, key=lambda page: page.id)
                ),
                "places": tuple(
                    p.model_copy(
                        update={
                            **CLEARED,
                            "id": places[p.id],
                            "name": Annotation(text=places[p.id]),
                            "place_type": None,
                        }
                    )
                    for p in sorted(container.places, key=lambda p: p.id)
                ),
                "transitions": tuple(
                    t.model_copy(
                        update={
                            **CLEARED,
                            "id": transitions[t.id],
                            "name": Annotation(text=transitions[t.id]),
                        }
                    )
                    for t in sorted(container.transitions, key=lambda t: t.id)
                ),
                "arcs": tuple(
                    a.model_copy(
                        update={
                            **CLEARED,
                            "id": arcs[a.id],
                            "source": both[a.source],
                            "target": both[a.target],
                            "name": None,
                        }
                    )
                    for a in sorted(container.arcs, key=lambda a: a.id)
                ),
                "ref_places": tuple(
                    r.model_copy(
                        update={**CLEARED, "id": places[r.id], "ref": places[r.ref], "name": None}
                    )
                    for r in sorted(container.ref_places, key=lambda r: r.id)
                ),
                "ref_transitions": tuple(
                    r.model_copy(
                        update={
                            **CLEARED,
                            "id": transitions[r.id],
                            "ref": transitions[r.ref],
                            "name": None,
                        }
                    )
                    for r in sorted(container.ref_transitions, key=lambda r: r.id)
                ),
            }
        )

    renamed = rewrite(container=document).model_copy(update={"source_id": "obfuscated"})
    return ObfuscatedNet(
        document=renamed,
        renamings=(
            *(Renaming(kind="place", original=o, obfuscated=n) for o, n in places.items()),
            *(
                Renaming(kind="transition", original=o, obfuscated=n)
                for o, n in transitions.items()
            ),
        ),
    )


def restore_expression(*, expression: Expression, renamings: tuple[Renaming, ...]) -> Expression:
    """Write a property about obfuscated names back in terms of the original ones."""
    places = {r.obfuscated: r.original for r in renamings if r.kind == "place"}
    transitions = {r.obfuscated: r.original for r in renamings if r.kind == "transition"}

    def back(*, node: Expression) -> Expression:  # noqa: PLR0911 - one branch per kind of node
        if isinstance(node, Tokens):
            return node.model_copy(update={"place": places[node.place]})
        if isinstance(node, Compare):
            sides = {
                side: (
                    value.model_copy(update={"places": tuple(places[p] for p in value.places)})
                    if isinstance(value, TokenCount)
                    else value
                )
                for side, value in (("left", node.left), ("right", node.right))
            }
            return node.model_copy(update=sides)
        if isinstance(node, Enabled):
            return node.model_copy(update={"transition": transitions[node.transition]})
        if isinstance(node, And | Or):
            return node.model_copy(update={"args": tuple(back(node=a) for a in node.args)})
        if isinstance(node, Not | LtlUnary | CtlUnary):
            return node.model_copy(update={"arg": back(node=node.arg)})
        if isinstance(node, Implies | LtlUntil | CtlUntil):
            return node.model_copy(
                update={"left": back(node=node.left), "right": back(node=node.right)}
            )
        return node  # deadlock and truth cite no element

    return back(node=expression)


def restore_formula(*, formula: Formula, renamings: tuple[Renaming, ...]) -> Formula:
    """Return the formula with the original names; the gloss is the model's and is kept as is."""
    return formula.model_copy(
        update={"ast": restore_expression(expression=formula.ast, renamings=renamings)}
    )
