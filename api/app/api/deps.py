"""FastAPI dependencies: the services built by the composition root (``app.main``)."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.application.agent import AgentService
from app.application.checks import CheckService
from app.application.descriptions import DescriptionService
from app.application.engines import EngineService
from app.application.formulas import FormulaService
from app.application.inspection import InspectionService
from app.application.nets import NetService
from app.application.retention import RetentionService


def get_nets(*, request: Request) -> NetService:
    """Return the net service of the running application."""
    return cast("NetService", request.app.state.nets)


def get_checks(*, request: Request) -> CheckService:
    """Return the check service of the running application."""
    return cast("CheckService", request.app.state.checks)


def get_engines(*, request: Request) -> EngineService:
    """Return the engine service of the running application."""
    return cast("EngineService", request.app.state.engines)


def get_inspection(*, request: Request) -> InspectionService:
    """Return the inspection service of the running application."""
    return cast("InspectionService", request.app.state.inspection)


def get_formulas(*, request: Request) -> FormulaService:
    """Return the formula service of the running application."""
    return cast("FormulaService", request.app.state.formulas)


def get_descriptions(*, request: Request) -> DescriptionService:
    """Return the description service of the running application."""
    return cast("DescriptionService", request.app.state.descriptions)


def get_agent(*, request: Request) -> AgentService:
    """Return the agent service of the running application."""
    return cast("AgentService", request.app.state.agent)


def get_retention(*, request: Request) -> RetentionService:
    """Return the retention service of the running application."""
    return cast("RetentionService", request.app.state.retention)


NetsDep = Annotated[NetService, Depends(get_nets)]
ChecksDep = Annotated[CheckService, Depends(get_checks)]
EnginesDep = Annotated[EngineService, Depends(get_engines)]
InspectionDep = Annotated[InspectionService, Depends(get_inspection)]
FormulasDep = Annotated[FormulaService, Depends(get_formulas)]
DescriptionsDep = Annotated[DescriptionService, Depends(get_descriptions)]
AgentDep = Annotated[AgentService, Depends(get_agent)]
RetentionDep = Annotated[RetentionService, Depends(get_retention)]
