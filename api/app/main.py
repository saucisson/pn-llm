"""Composition root: the only place that knows every layer and wires them together.

Run:  uvicorn app.main:create_app --factory --reload
Several worker processes on the same host are supported (job leases, see ADR 0003).
There is deliberately no module-level ``app``: importing this module has no side effect.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api import engines, jobs, nets
from app.api.errors import register_error_handlers
from app.application.checks import CheckService
from app.application.engines import EngineService
from app.application.nets import NetService
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.sqlite_store import SqliteStore
from app.settings import Settings


def create_app(*, settings: Settings | None = None) -> FastAPI:
    """Build the application from its settings (read from the environment when omitted)."""
    config = settings or Settings()

    store = SqliteStore(path=config.database_path)
    registry = EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    checks = CheckService(
        nets=store, jobs=store, engines=registry, lease_seconds=config.job_lease_seconds
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Every process sweeps expired leases, so orphans are found whichever process survives.
        async def sweep() -> None:
            while True:
                await run_in_threadpool(checks.recover_interrupted)
                await asyncio.sleep(config.job_lease_seconds / 2)

        sweeper = asyncio.create_task(sweep())
        try:
            yield
        finally:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper

    app = FastAPI(title="pn-llm-verif", version=__version__, lifespan=lifespan)
    app.state.nets = NetService(nets=store, max_pnml_bytes=config.max_pnml_bytes)
    app.state.checks = checks
    app.state.engines = EngineService(engines=registry)
    register_error_handlers(app=app)
    for module in (nets, jobs, engines):
        app.include_router(module.router)
    return app
