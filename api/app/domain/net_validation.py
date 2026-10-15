"""Validation shared by both input formats: structure, references and size bounds."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError

from .errors import InvalidNetError
from .models import DomainModel
from .net_document import NetDocument


class DocumentLimits(DomainModel):
    """Bounds on what a document may contain; exceeding one is a 422, never a crash.

    The depth of XML trees is bounded by the parsers (the PNML importer, pydantic for JSON).
    """

    max_elements: int = Field(default=5_000_000, ge=1)
    max_page_depth: int = Field(default=32, ge=1)
    max_string_length: int = Field(default=65_536, ge=1)


class Entry(DomainModel):
    """One page, node or arc met while walking a document."""

    id: str
    role: Literal["page", "place", "transition", "arc"]
    location: str  # JSON pointer to the element
    ref: str | None = None
    source: str | None = None
    target: str | None = None


def parse_document(*, payload: bytes, limits: DocumentLimits) -> NetDocument:
    """Read a JSON net document and validate it.

    Raises:
        InvalidNetError: if the JSON does not describe a valid net; ``location`` is a JSON pointer.
    """
    try:
        document = NetDocument.model_validate_json(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        pointer = "".join(f"/{part}" for part in first["loc"])
        raise InvalidNetError(first["msg"], location=pointer or "/") from exc
    validate_document(document=document, limits=limits)
    return document


def validate_document(*, document: NetDocument, limits: DocumentLimits) -> None:
    """Check ids, arcs, references, integer P/T markings and size bounds.

    Raises:
        InvalidNetError: on the first fault found, with a JSON pointer to it.
    """
    check_entries(entries=list_entries(document=document, limits=limits), limits=limits)


def list_entries(*, document: NetDocument, limits: DocumentLimits) -> tuple[Entry, ...]:
    """Walk the page tree and list every page, node and arc, checking P/T values and depth."""
    is_pt = document.kind == "pt"
    entries: list[Entry] = []
    for located in document.located_containers():
        container, pointer = located.container, located.pointer
        if located.depth > limits.max_page_depth:
            raise InvalidNetError("pages are nested too deeply", location=pointer)
        if located.page_id is not None:
            entries.append(Entry(id=located.page_id, role="page", location=pointer))

        for index, place in enumerate(container.places):
            entries.append(Entry(id=place.id, role="place", location=f"{pointer}/places/{index}"))
            marking = place.initial_marking
            if (
                is_pt
                and marking is not None
                and marking.text is not None
                and not (marking.text.isascii() and marking.text.isdigit())
            ):
                raise InvalidNetError(
                    "a P/T initial marking is a non-negative integer",
                    location=f"{pointer}/places/{index}/initial_marking/text",
                )
        for index, transition in enumerate(container.transitions):
            entries.append(
                Entry(
                    id=transition.id, role="transition", location=f"{pointer}/transitions/{index}"
                )
            )
        for index, ref in enumerate(container.ref_places):
            entries.append(
                Entry(
                    id=ref.id, role="place", ref=ref.ref, location=f"{pointer}/ref_places/{index}"
                )
            )
        for index, ref_transition in enumerate(container.ref_transitions):
            entries.append(
                Entry(
                    id=ref_transition.id,
                    role="transition",
                    ref=ref_transition.ref,
                    location=f"{pointer}/ref_transitions/{index}",
                )
            )
        for index, arc in enumerate(container.arcs):
            entries.append(
                Entry(
                    id=arc.id,
                    role="arc",
                    source=arc.source,
                    target=arc.target,
                    location=f"{pointer}/arcs/{index}",
                )
            )
            inscription = arc.inscription
            if (
                is_pt
                and inscription is not None
                and inscription.text is not None
                and (
                    not inscription.text.isascii()
                    or not inscription.text.isdigit()
                    or int(inscription.text) < 1
                )
            ):
                raise InvalidNetError(
                    "a P/T arc inscription is a positive integer",
                    location=f"{pointer}/arcs/{index}/inscription/text",
                )

    return tuple(entries)


def check_entries(*, entries: tuple[Entry, ...], limits: DocumentLimits) -> None:
    """Check bounds, unique ids, arc ends and references over a document's entries."""
    if len(entries) > limits.max_elements:
        raise InvalidNetError("too many elements", location="/")

    roles: dict[str, str] = {}
    refs_of: dict[str, str] = {}
    for entry in entries:
        if len(entry.id) > limits.max_string_length:
            raise InvalidNetError("id too long", location=f"{entry.location}/id")
        if entry.id in roles:
            raise InvalidNetError(f"duplicate id {entry.id!r}", location=f"{entry.location}/id")
        roles[entry.id] = entry.role
        if entry.ref is not None:
            refs_of[entry.id] = entry.ref

    for entry in entries:
        if entry.role == "arc":
            for end, field in ((entry.source, "source"), (entry.target, "target")):
                if roles.get(end or "") not in {"place", "transition"}:
                    raise InvalidNetError(
                        f"arc {entry.id!r} {field} {end!r} is not a place or a transition",
                        location=entry.location + f"/{field}",
                    )
            if roles[entry.source or ""] == roles[entry.target or ""]:
                raise InvalidNetError(
                    f"arc {entry.id!r} must join a place and a transition",
                    location=entry.location,
                )
        if entry.ref is not None:
            # Follow the chain of references; a cycle never reaches a real node.
            followed = {entry.id}
            current = entry.ref
            while current in refs_of:
                if current in followed:
                    raise InvalidNetError(
                        f"reference {entry.id!r} is part of a cycle",
                        location=entry.location + "/ref",
                    )
                followed.add(current)
                current = refs_of[current]
            if roles.get(current) != entry.role:
                raise InvalidNetError(
                    f"reference {entry.id!r} does not resolve to a {entry.role}",
                    location=entry.location + "/ref",
                )
