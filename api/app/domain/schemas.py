"""JSON Schemas of the public models, rendered deterministically for the committed copies."""

from __future__ import annotations

import json

from pydantic import BaseModel

from .contract import ElementRef, Envelope, Marking, Page, PageRequest
from .models import CheckRequest, EngineInfo, FormulaResult

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    CheckRequest,
    ElementRef,
    EngineInfo,
    Envelope,
    FormulaResult,
    Marking,
    Page,
    PageRequest,
)


def render_schema(*, model: type[BaseModel]) -> str:
    """Return the JSON Schema of ``model`` as stable text: sorted keys, trailing newline."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
