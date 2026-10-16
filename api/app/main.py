"""Composition root: the only module that knows every layer (docs/architecture.md)."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import threading
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api import (
    descriptions,
    engines,
    formulas,
    inspection,
    jobs,
    models,
    nets,
    operations,
    sessions,
)
from app.api.errors import register_error_handlers
from app.api.middleware import log_requests
from app.application.agent import AgentConfig, AgentService
from app.application.analysis_tools import AnalysisTools
from app.application.checks import CheckService
from app.application.descriptions import DescriptionService
from app.application.engines import EngineService
from app.application.formulas import FormulaService
from app.application.inspection import InspectionService
from app.application.models import ModelCatalogService
from app.application.nets import NetService
from app.application.operations import OperationService
from app.application.ports import EngineGateway, LlmGateway
from app.application.results import ResultsService
from app.application.retention import RetentionService
from app.application.selection import SelectionService
from app.application.splits import SplitService
from app.application.tools import ToolFacade
from app.application.traces import TraceService
from app.application.workers import WorkerPool
from app.infrastructure.anthropic_llm import AnthropicLlm
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.json_logging import configure_logging
from app.infrastructure.scripted_llm import DemoLlm
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_operations import SqliteOperations
from app.infrastructure.sqlite_results import SqliteResults
from app.infrastructure.sqlite_retention import SqliteRetention
from app.infrastructure.sqlite_splits import SqliteSplits
from app.infrastructure.sqlite_store import SqliteStore
from app.infrastructure.unavailable_llm import UnavailableLlm
from app.settings import Settings

SECONDS_PER_DAY = 86_400


def build_llm(*, config: Settings) -> LlmGateway:
    """Return the language model the settings ask for."""
    if config.llm_provider == "scripted":
        return DemoLlm()
    if config.llm_provider == "anthropic":
        if config.anthropic_api_key is None:
            return UnavailableLlm(
                reason="PNVERIF_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) is not set"
            )
        return AnthropicLlm(
            api_key=config.anthropic_api_key.get_secret_value(),
            model=config.anthropic_model,
            max_tokens=config.anthropic_max_tokens,
        )
    return UnavailableLlm()


def build_agent(
    *,
    config: Settings,
    store: SqliteStore,
    checks: CheckService,
    operations: OperationService,
    llm: LlmGateway,
) -> AgentService:
    """Wire the agent over the store, the use cases it exposes as tools, and a language model."""
    tools = ToolFacade(
        inspection=InspectionService(nets=store),
        formulas=FormulaService(nets=store),
        checks=checks,
        analyses=AnalysisTools(
            operations=operations,
            poll_seconds=config.tool_poll_seconds,
            summary_max_chars=config.analysis_summary_max_chars,
        ),
        max_result_chars=config.tool_result_max_chars,
        poll_seconds=config.tool_poll_seconds,
    )
    return AgentService(
        sessions=store,
        descriptions=store,
        nets=store,
        llm=llm,
        tools=tools,
        config=AgentConfig(
            max_steps=config.agent_max_steps,
            max_tool_calls=config.agent_max_tool_calls,
            max_tokens=config.agent_max_tokens,
            max_seconds=config.agent_max_seconds,
            lease_seconds=config.job_lease_seconds,
        ),
    )


def build_retention(
    *, config: Settings, store: SqliteStore, agent: AgentService
) -> RetentionService:
    """Wire the deletion of user data."""
    return RetentionService(
        retention=SqliteRetention(path=config.database_path),
        agent=agent,
        nets=store,
        descriptions=store,
    )


def build_operations(
    *, config: Settings, store: SqliteStore, engines: EngineGateway
) -> OperationService:
    """Return the operation service over the database and the engines."""
    return OperationService(
        nets=store,
        net_service=NetService(
            nets=store,
            max_upload_bytes=config.max_upload_bytes,
            limits=config.document_limits(),
        ),
        runs=SqliteOperations(path=config.database_path),
        engines=engines,
        lease_seconds=config.job_lease_seconds,
        wait_seconds=config.operation_wait_seconds,
    )


def sweep_once(
    *,
    config: Settings,
    checks: CheckService,
    operations: OperationService,
    agent: AgentService,
    retention: RetentionService,
) -> None:
    """Find lost work and apply the retention policy: leases, runs, old jobs, sessions, nets."""
    checks.recover_interrupted()
    operations.recover_interrupted()
    agent.recover_lost_runs()
    if config.job_retention_days is not None:
        checks.purge_old_jobs(retention_s=config.job_retention_days * SECONDS_PER_DAY)
        operations.purge_old_runs(retention_s=config.job_retention_days * SECONDS_PER_DAY)
    if config.session_waiting_expiry_days is not None:
        agent.expire_waiting(older_than_s=config.session_waiting_expiry_days * SECONDS_PER_DAY)
    retention.expire(
        sessions_older_than_s=None
        if config.session_retention_days is None
        else config.session_retention_days * SECONDS_PER_DAY,
        nets_older_than_s=None
        if config.unreferenced_net_retention_days is None
        else config.unreferenced_net_retention_days * SECONDS_PER_DAY,
    )


def create_app(
    *,
    settings: Settings | None = None,
    engine_gateway: EngineGateway | None = None,
    llm_gateway: LlmGateway | None = None,
) -> FastAPI:
    """Build the application from its settings (read from the environment when omitted).

    ``engine_gateway`` and ``llm_gateway`` replace the Docker-backed engines and the configured
    language model: the seams for tests that need a scripted answer.
    """
    config = settings or Settings()
    configure_logging(level=config.log_level, as_json=config.log_json)

    store = SqliteStore(path=config.database_path)
    registry = engine_gateway or EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    checks = CheckService(
        nets=store, jobs=store, engines=registry, lease_seconds=config.job_lease_seconds
    )
    operations_service = build_operations(config=config, store=store, engines=registry)
    agent = build_agent(
        config=config,
        store=store,
        checks=checks,
        operations=operations_service,
        llm=llm_gateway or build_llm(config=config),
    )
    retention = build_retention(config=config, store=store, agent=agent)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Every process sweeps expired leases, so orphans are found whichever process survives.
        async def sweep() -> None:
            while True:
                await run_in_threadpool(
                    sweep_once,
                    config=config,
                    checks=checks,
                    operations=operations_service,
                    agent=agent,
                    retention=retention,
                )
                await asyncio.sleep(config.job_lease_seconds / 2)

        sweeper = asyncio.create_task(sweep())
        with contextlib.ExitStack() as workers:
            if config.embedded_workers > 0:
                workers.enter_context(
                    WorkerPool(
                        runners=(checks.run_next, operations_service.run_next, agent.run_next),
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
        nets=store, max_upload_bytes=config.max_upload_bytes, limits=config.document_limits()
    )
    app.state.models = ModelCatalogService(
        catalog=SqliteCatalog(path=config.database_path),
        nets=app.state.nets,
        descriptions=store,
    )
    app.state.splits = SplitService(
        splits=SqliteSplits(path=config.database_path),
        catalog=SqliteCatalog(path=config.database_path),
    )
    app.state.results = ResultsService(results=SqliteResults(path=config.database_path))
    app.state.checks = checks
    app.state.operations = operations_service
    app.state.selection = SelectionService(
        nets=store, engines=registry, results=SqliteResults(path=config.database_path)
    )
    app.state.traces = TraceService(
        checks=checks, nets=store, lineage=SqliteOperations(path=config.database_path)
    )
    app.state.inspection = InspectionService(nets=store)
    app.state.formulas = FormulaService(nets=store)
    app.state.descriptions = DescriptionService(
        nets=store, descriptions=store, max_bytes=config.max_description_bytes
    )
    app.state.agent = agent
    app.state.retention = retention
    app.state.engines = EngineService(engines=registry)
    register_error_handlers(app=app)
    app.middleware("http")(log_requests)
    if config.ui_dir is not None and config.ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=config.ui_dir, html=True), name="ui")
    for module in (
        nets,
        descriptions,
        inspection,
        formulas,
        jobs,
        operations,
        sessions,
        engines,
        models,
    ):
        app.include_router(module.router)
    return app


def worker_main() -> None:
    """Run workers in this process only (``python -m app.main``), until interrupted.

    Workers of several processes share the queues in the database; the lease sweeper runs in
    API processes and here too, so lost work is found whichever process survives.
    """
    config = Settings()
    configure_logging(level=config.log_level, as_json=config.log_json)
    store = SqliteStore(path=config.database_path)
    registry = EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    checks = CheckService(
        nets=store, jobs=store, engines=registry, lease_seconds=config.job_lease_seconds
    )
    operations_service = build_operations(config=config, store=store, engines=registry)
    agent = build_agent(
        config=config,
        store=store,
        checks=checks,
        operations=operations_service,
        llm=build_llm(config=config),
    )
    retention = build_retention(config=config, store=store, agent=agent)
    stopping = threading.Event()
    handler: Callable[..., None] = lambda *_: stopping.set()  # noqa: E731 - signal handler
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handler)
    with WorkerPool(
        runners=(checks.run_next, operations_service.run_next, agent.run_next),
        size=config.worker_threads,
        poll_seconds=config.worker_poll_seconds,
    ):
        while not stopping.wait(timeout=config.job_lease_seconds / 2):
            sweep_once(
                config=config,
                checks=checks,
                operations=operations_service,
                agent=agent,
                retention=retention,
            )


if __name__ == "__main__":
    worker_main()
