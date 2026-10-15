"""Minimal reader for P/T PNML (enough for the prototype)."""

from __future__ import annotations

import contextlib
import hashlib
from xml.etree.ElementTree import ParseError  # exception type only: parsing uses defusedxml

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET  # hardened against entity-expansion attacks

from .errors import PnmlError
from .models import NetSummary

NET_ID_LENGTH = 16


def summarize(*, pnml: bytes) -> NetSummary:
    """Parse a PNML document and return its summary.

    Names are kept exactly as written: they carry the meaning the LLM relies on. Namespaces are
    ignored, a missing name falls back to the element id, and a non-numeric initial marking
    counts as zero.

    Raises:
        PnmlError: if the XML is invalid or the net has no place or no transition.
    """
    try:
        root = SafeET.fromstring(pnml)
    except (ParseError, DefusedXmlException) as exc:
        raise PnmlError(f"Invalid XML: {exc}") from exc

    place_names: list[str] = []
    transition_names: list[str] = []
    arcs = 0
    tokens = 0
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "arc":
            arcs += 1
            continue
        if tag not in {"place", "transition"}:
            continue

        # First <text> inside each of the <name> and <initialMarking> children.
        texts: dict[str, str] = {}
        for child in element.iter():
            child_tag = child.tag.rsplit("}", 1)[-1]
            if child_tag not in {"name", "initialMarking"}:
                continue
            for leaf in child.iter():
                if leaf.tag.rsplit("}", 1)[-1] == "text" and leaf.text:
                    texts.setdefault(child_tag, leaf.text.strip())
        name = texts.get("name") or str(element.get("id", ""))

        if tag == "transition":
            transition_names.append(name)
            continue
        place_names.append(name)
        with contextlib.suppress(ValueError):
            tokens += int(texts.get("initialMarking", "0"))

    if not place_names or not transition_names:
        raise PnmlError("Empty net: at least one place and one transition are required")

    return NetSummary(
        net_id=hashlib.sha256(pnml).hexdigest()[:NET_ID_LENGTH],
        places=len(place_names),
        transitions=len(transition_names),
        arcs=arcs,
        place_names=tuple(place_names),
        transition_names=tuple(transition_names),
        initial_tokens=tokens,
    )
