"""JSON Schemas of the public models, rendered deterministically for the committed copies."""

from __future__ import annotations

import json

from pydantic import BaseModel

from .contract import ElementRef, Envelope, Marking, Page, PageRequest
from .descriptions import Description
from .engine_contract import EngineCheckData, EngineRequest, EngineTrace, Trace
from .formula import Formula
from .formula_check import FormulaReport, FormulaValidationRequest
from .inspection import ArcView, ElementDetail, NameGroup, Neighbourhood, NetOverview
from .models import CheckRequest, EngineInfo, FormulaResult
from .net_document import NetDocument
from .nets import NetRegistration
from .replay import ReplayRequest, ReplayResult

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    ArcView,
    CheckRequest,
    Description,
    ElementDetail,
    ElementRef,
    EngineCheckData,
    EngineInfo,
    EngineRequest,
    EngineTrace,
    Envelope,
    Formula,
    FormulaReport,
    FormulaResult,
    FormulaValidationRequest,
    Marking,
    NameGroup,
    Neighbourhood,
    NetDocument,
    NetOverview,
    NetRegistration,
    Page,
    PageRequest,
    ReplayRequest,
    ReplayResult,
    Trace,
)


def render_schema(*, model: type[BaseModel]) -> str:
    """Return the JSON Schema of ``model`` as stable text: sorted keys, trailing newline."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
