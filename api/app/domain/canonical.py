"""Canonical form and identity of a net document (ADR 0015, RFC 8785).

The canonical JSON has sorted keys, no white space, UTF-8, omits absent and default values and
orders the children of each container by id. The net id is the first 32 hex characters of the
SHA-256 of those bytes. ``schema_version`` is not part of the hash.
"""

from __future__ import annotations

import hashlib
import json
import math

from pydantic import JsonValue

from .net_document import NetDocument

NET_ID_LENGTH = 32


def canonical_number(*, value: float) -> str:
    """Format a number as ECMAScript does (RFC 8785): integral values without a fraction."""
    if not math.isfinite(value):
        message = "a non-finite number has no canonical form"
        raise ValueError(message)
    if value == int(value) and abs(value) < 1e21:  # noqa: PLR2004 - ECMAScript switches to exponent here
        return str(int(value))
    text = repr(value)
    # Python writes 1e-07 where ECMAScript writes 1e-7 (the sign is kept: 1e+22).
    mantissa, _, exponent = text.partition("e")
    if not exponent:
        return text
    sign = "-" if exponent.startswith("-") else "+"
    return f"{mantissa}e{sign}{exponent.lstrip('+-').lstrip('0')}"


def canonical_json(*, value: JsonValue) -> str:
    """Serialize any JSON value as RFC 8785 canonical JSON text."""
    if isinstance(value, dict):
        # JCS sorts keys by UTF-16 code units, which differs from code points beyond the BMP.
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        members = (
            f"{json.dumps(key, ensure_ascii=False)}:{canonical_json(value=value[key])}"
            for key in keys
        )
        return "{" + ",".join(members) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(value=item) for item in value) + "]"
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return canonical_number(value=value)


def canonical_bytes(*, document: NetDocument) -> bytes:
    """Return the canonical UTF-8 bytes of a document: what is stored and hashed."""
    plain = document.sorted_by_id().model_dump(
        mode="json", exclude_none=True, exclude_defaults=True, exclude={"schema_version"}
    )
    return canonical_json(value=plain).encode("utf-8")


def net_id_of(*, document: NetDocument) -> str:
    """Return the identity of a net: a truncated SHA-256 of its canonical form."""
    return hashlib.sha256(canonical_bytes(document=document)).hexdigest()[:NET_ID_LENGTH]
