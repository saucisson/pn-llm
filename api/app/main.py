"""Composition root: the only place that knows every layer and wires them together.

Run:  uvicorn app.main:create_app --factory --reload
Several worker processes on the same host are supported (job leases, see ADR 0003).
There is deliberately no module-level ``app``: importing this module has no side effect.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import threading
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api import descriptions, engines, formulas, inspection, jobs, nets
from app.api.errors import register_error_handlers
from app.application.checks import CheckService
from app.application.descriptions import DescriptionService
from app.application.engines import EngineService
from app.application.formulas import FormulaService
from app.application.inspection import InspectionService
from app.application.nets import NetService
from app.application.ports import EngineGateway
from app.application.workers import WorkerPool
from app.domain.net_validation import DocumentLimits
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.sqlite_store import SqliteStore
from app.settings import Settings

SECONDS_PER_DAY = 86_400


def create_app(
    *, settings: Settings | None = None, engine_gateway: EngineGateway | None = None
) -> FastAPI:
    """Build the application from its settings (read from the environment when omitted).

    ``engine_gateway`` replaces the Docker-backed engine registry: the seam for tests that need
    an engine with a scripted answer.
    """
    config = settings or Settings()

    store = SqliteStore(path=config.database_path)
    registry = engine_gateway or EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    checks = CheckService(
        nets=store, jobs=store, engines=registry, lease_seconds=config.job_lease_seconds
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Every process sweeps expired leases, so orphans are found whichever process survives.
        async def sweep() -> None:
            while True:
                await run_in_threadpool(checks.recover_interrupted)
                if config.job_retention_days is not None:
                    await run_in_threadpool(
                        checks.purge_old_jobs,
                        retention_s=config.job_retention_days * SECONDS_PER_DAY,
                    )
                await asyncio.sleep(config.job_lease_seconds / 2)

        sweeper = asyncio.create_task(sweep())
        with contextlib.ExitStack() as workers:
            if config.embedded_workers > 0:
                workers.enter_context(
                    WorkerPool(
                        checks=checks,
                        size=config.embedded_workers,
                        poll_seconds=config.worker_poll_seconds,
                    )
                )
            try:
                yield
            finally:
                sweeper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sweeper
                # Stopping waits for the jobs in progress: not on the event loop.
                await run_in_threadpool(workers.close)

    app = FastAPI(title="pn-llm-verif", version=__version__, lifespan=lifespan)
    app.state.nets = NetService(
        nets=store,
        max_upload_bytes=config.max_upload_bytes,
        limits=DocumentLimits(
            max_elements=config.max_net_elements,
            max_page_depth=config.max_page_depth,
            max_xml_depth=config.max_xml_depth,
            max_string_length=config.max_string_length,
        ),
    )
    app.state.checks = checks
    app.state.inspection = InspectionService(nets=store)
    app.state.formulas = FormulaService(nets=store)
    app.state.descriptions = DescriptionService(
        nets=store, descriptions=store, max_bytes=config.max_description_bytes
    )
    app.state.engines = EngineService(engines=registry)
    register_error_handlers(app=app)
    if config.ui_dir is not None and config.ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=config.ui_dir, html=True), name="ui")
    for module in (nets, descriptions, inspection, formulas, jobs, engines):
        app.include_router(module.router)
    return app


def worker_main() -> None:
    """Run job workers in this process only (``python -m app.main``), until interrupted.

    Workers of several processes share the one queue in the database; the lease sweeper runs in
    API processes and here too, so lost jobs are found whichever process survives.
    """
    config = Settings()
    store = SqliteStore(path=config.database_path)
    checks = CheckService(
        nets=store,
        jobs=store,
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner()),
        lease_seconds=config.job_lease_seconds,
    )
    stopping = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())
    with WorkerPool(
        checks=checks, size=config.worker_threads, poll_seconds=config.worker_poll_seconds
    ):
        while not stopping.wait(timeout=config.job_lease_seconds / 2):
            checks.recover_interrupted()


if __name__ == "__main__":
    worker_main()
