"""Net descriptions: what a model represents, in the words of whoever knows it (ADR 0011).

A description is an immutable text identified by the hash of its UTF-8 bytes, stored exactly as
sent. A net can have several, each linked to it with an origin. A description is untrusted data
like a place name: it is never interpreted as instructions (ADR 0009).
"""

from __future__ import annotations

import hashlib
from typing import Literal

from .models import DomainModel

DESCRIPTION_ID_LENGTH = 32

DescriptionOrigin = Literal["user", "mcc", "llm"]


class Description(DomainModel):
    """A description of a net, with the origin of the link to that net."""

    description_id: str
    net_id: str
    origin: DescriptionOrigin
    text: str


class SavedDescription(DomainModel):
    """Result of adding a description: what is stored and whether this call created the link."""

    description: Description
    created: bool


def description_id_of(*, text: str) -> str:
    """Return the identity of a description: a truncated SHA-256 of its UTF-8 bytes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:DESCRIPTION_ID_LENGTH]
