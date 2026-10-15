"""The net a reduction produced, as a net document ready to be stored."""

from __future__ import annotations

from app.domain.net_document import (
    PTNET_TYPE_URI,
    Annotation,
    Arc,
    NetDocument,
    Page,
    Place,
    Transition,
)
from app.domain.net_structure import NetStructure


def structure_to_document(*, structure: NetStructure, source_id: str) -> NetDocument:
    """Write a P/T structure as a one-page net document.

    Ids and names are kept as they are; graphics and tool-specific data are not carried over,
    because a reduced net is built for engines, not for editing.
    """
    return NetDocument(
        source_id=source_id,
        type_uri=PTNET_TYPE_URI,
        pages=(
            Page(
                id="reduced",
                places=tuple(
                    Place(
                        id=place.id,
                        name=None if place.name is None else Annotation(text=place.name),
                        initial_marking=(
                            Annotation(text=str(place.tokens)) if place.tokens else None
                        ),
                    )
                    for place in structure.places
                ),
                transitions=tuple(
                    Transition(
                        id=transition.id,
                        name=None if transition.name is None else Annotation(text=transition.name),
                    )
                    for transition in structure.transitions
                ),
                arcs=tuple(
                    Arc(
                        id=arc.id,
                        source=arc.source,
                        target=arc.target,
                        inscription=(
                            Annotation(text=str(arc.weight))
                            if arc.weight not in {None, 1}
                            else None
                        ),
                    )
                    for arc in structure.arcs
                ),
            ),
        ),
    )
