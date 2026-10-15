"""FastAPI dependencies: the services built by the composition root (``app.main``)."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.application.checks import CheckService
from app.application.engines import EngineService
from app.application.nets import NetService


def get_nets(*, request: Request) -> NetService:
    """Return the net service of the running application."""
    return cast("NetService", request.app.state.nets)


def get_checks(*, request: Request) -> CheckService:
    """Return the check service of the running application."""
    return cast("CheckService", request.app.state.checks)


def get_engines(*, request: Request) -> EngineService:
    """Return the engine service of the running application."""
    return cast("EngineService", request.app.state.engines)


NetsDep = Annotated[NetService, Depends(get_nets)]
ChecksDep = Annotated[CheckService, Depends(get_checks)]
EnginesDep = Annotated[EngineService, Depends(get_engines)]
