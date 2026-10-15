"""HTTP content negotiation for the net endpoints (Content-Type and Accept)."""

from __future__ import annotations

from app.domain.models import DomainModel

JSON = "application/json"
PNML = "application/pnml+xml"
PNML_REQUEST_TYPES = frozenset({PNML, "application/xml", "text/xml"})


class MediaRange(DomainModel):
    """One entry of an Accept header."""

    type: str
    quality: float


def media_type_of(*, content_type: str | None) -> str:
    """Return the media type of a Content-Type header, lower case, without parameters."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def parse_accept(*, header: str) -> tuple[MediaRange, ...]:
    """Parse an Accept header; an entry with a bad quality counts as quality 0."""
    ranges: list[MediaRange] = []
    for entry in header.split(","):
        pieces = [piece.strip() for piece in entry.split(";")]
        if not pieces[0]:
            continue
        quality = 1.0
        for parameter in pieces[1:]:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        ranges.append(MediaRange(type=pieces[0].lower(), quality=quality))
    return tuple(ranges)


def negotiate(*, accept: str | None, offered: tuple[str, ...]) -> str | None:
    """Pick the offered media type the client prefers; None if it accepts none of them.

    An absent header accepts everything. Ties go to the first offered type, so list the default
    first. The most specific matching range decides the quality of an offered type.
    """
    if accept is None or not accept.strip():
        return offered[0]
    ranges = parse_accept(header=accept)
    best: str | None = None
    best_quality = 0.0
    for candidate in offered:
        family = candidate.split("/", 1)[0] + "/*"
        matching = [r for r in ranges if r.type in {candidate, family, "*/*"}]
        if not matching:
            continue
        exact = [r for r in matching if r.type == candidate]
        wildcard_family = [r for r in matching if r.type == family]
        decisive = (exact or wildcard_family or matching)[0]
        if decisive.quality > best_quality:
            best, best_quality = candidate, decisive.quality
    return best
