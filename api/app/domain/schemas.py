"""JSON Schemas of the public models, rendered deterministically for the committed copies."""

from __future__ import annotations

import json

from pydantic import BaseModel

from .contract import ElementRef, Envelope, Marking, Page, PageRequest
from .inspection import ArcView, ElementDetail, NameGroup, Neighbourhood, NetOverview
from .models import CheckRequest, EngineInfo, FormulaResult
from .net_document import NetDocument
from .nets import NetRegistration

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    ArcView,
    CheckRequest,
    ElementDetail,
    ElementRef,
    EngineInfo,
    Envelope,
    FormulaResult,
    Marking,
    NameGroup,
    Neighbourhood,
    NetDocument,
    NetOverview,
    NetRegistration,
    Page,
    PageRequest,
)


def render_schema(*, model: type[BaseModel]) -> str:
    """Return the JSON Schema of ``model`` as stable text: sorted keys, trailing newline."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
