"""Detect a net (PNML, XML or a net document) in text that is about to reach the LLM.

The LLM learns about a net through inspection tools only (ADR 0013, ADR 0015). This check is a
second line of defence next to the tool list: tools offered to the LLM must pass their output
through it, and tests use it to prove the tool list is clean.
"""

from __future__ import annotations

import json

from pydantic import JsonValue, ValidationError

from .net_document import NetDocument

XML_MARKERS = ("<pnml", "<?xml")


def holds_net_document(*, value: JsonValue) -> bool:
    """Tell whether a JSON value is, or contains, something that validates as a net document."""
    if isinstance(value, dict):
        if "source_id" in value and "type_uri" in value:
            try:
                NetDocument.model_validate(value)
            except ValidationError:
                pass
            else:
                return True
        return any(holds_net_document(value=item) for item in value.values())
    if isinstance(value, list):
        return any(holds_net_document(value=item) for item in value)
    return False


def contains_net(*, text: str) -> bool:
    """Tell whether ``text`` holds PNML, an XML declaration or a JSON net document."""
    lowered = text.lower()
    if any(marker in lowered for marker in XML_MARKERS):
        return True
    try:
        parsed: JsonValue = json.loads(text)
    except ValueError:
        return False
    return holds_net_document(value=parsed)
