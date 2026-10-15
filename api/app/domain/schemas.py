"""JSON Schemas of the public models, rendered deterministically for the committed copies."""

from __future__ import annotations

import json

from pydantic import BaseModel

from .contract import ElementRef, Envelope, Marking, Page, PageRequest
from .descriptions import Description
from .engine_contract import (
    EngineCheckData,
    EngineOperationData,
    EngineRequest,
    EngineTrace,
    Trace,
)
from .formula import Formula
from .formula_check import FormulaReport, FormulaValidationRequest
from .inspection import ArcView, ElementDetail, NameGroup, Neighbourhood, NetOverview
from .models import CheckRequest, EngineInfo, FormulaResult
from .net_document import NetDocument
from .nets import NetRegistration
from .operations import OperationDescription
from .replay import ReplayRequest, ReplayResult
from .report import SessionReport
from .sessions import Session, StoredEvent

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    ArcView,
    CheckRequest,
    Description,
    ElementDetail,
    ElementRef,
    EngineCheckData,
    EngineInfo,
    EngineOperationData,
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
    OperationDescription,
    Page,
    PageRequest,
    ReplayRequest,
    ReplayResult,
    Session,
    SessionReport,
    StoredEvent,
    Trace,
)


def render_schema(*, model: type[BaseModel]) -> str:
    """Return the JSON Schema of ``model`` as stable text: sorted keys, trailing newline."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
