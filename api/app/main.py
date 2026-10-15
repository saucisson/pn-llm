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
from app.api import descriptions, engines, formulas, inspection, jobs, nets, sessions
from app.api.errors import register_error_handlers
from app.application.agent import AgentConfig, AgentService
from app.application.checks import CheckService
from app.application.descriptions import DescriptionService
from app.application.engines import EngineService
from app.application.formulas import FormulaService
from app.application.inspection import InspectionService
from app.application.nets import NetService
from app.application.ports import EngineGateway, LlmGateway
from app.application.tools import ToolFacade
from app.application.workers import WorkerPool
from app.domain.net_validation import DocumentLimits
from app.infrastructure.anthropic_llm import AnthropicLlm
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.scripted_llm import DemoLlm
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
    *, config: Settings, store: SqliteStore, checks: CheckService, llm: LlmGateway
) -> AgentService:
    """Wire the agent over the store, the use cases it exposes as tools, and a language model."""
    tools = ToolFacade(
        inspection=InspectionService(nets=store),
        formulas=FormulaService(nets=store),
        checks=checks,
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


def sweep_once(*, config: Settings, checks: CheckService, agent: AgentService) -> None:
    """Find lost work: expired leases, runs to resume, old finished jobs, abandoned questions."""
    checks.recover_interrupted()
    agent.recover_lost_runs()
    if config.job_retention_days is not None:
        checks.purge_old_jobs(retention_s=config.job_retention_days * SECONDS_PER_DAY)
    if config.session_waiting_expiry_days is not None:
        agent.expire_waiting(older_than_s=config.session_waiting_expiry_days * SECONDS_PER_DAY)


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

    store = SqliteStore(path=config.database_path)
    registry = engine_gateway or EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    checks = CheckService(
        nets=store, jobs=store, engines=registry, lease_seconds=config.job_lease_seconds
    )
    agent = build_agent(
        config=config, store=store, checks=checks, llm=llm_gateway or build_llm(config=config)
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Every process sweeps expired leases, so orphans are found whichever process survives.
        async def sweep() -> None:
            while True:
                await run_in_threadpool(sweep_once, config=config, checks=checks, agent=agent)
                await asyncio.sleep(config.job_lease_seconds / 2)

        sweeper = asyncio.create_task(sweep())
        with contextlib.ExitStack() as workers:
            if config.embedded_workers > 0:
                workers.enter_context(
                    WorkerPool(
                        runners=(checks.run_next, agent.run_next),
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
    app.state.agent = agent
    app.state.engines = EngineService(engines=registry)
    register_error_handlers(app=app)
    if config.ui_dir is not None and config.ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=config.ui_dir, html=True), name="ui")
    for module in (nets, descriptions, inspection, formulas, jobs, sessions, engines):
        app.include_router(module.router)
    return app


def worker_main() -> None:
    """Run workers in this process only (``python -m app.main``), until interrupted.

    Workers of several processes share the queues in the database; the lease sweeper runs in
    API processes and here too, so lost work is found whichever process survives.
    """
    config = Settings()
    store = SqliteStore(path=config.database_path)
    checks = CheckService(
        nets=store,
        jobs=store,
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner()),
        lease_seconds=config.job_lease_seconds,
    )
    agent = build_agent(config=config, store=store, checks=checks, llm=build_llm(config=config))
    stopping = threading.Event()
    handler: Callable[..., None] = lambda *_: stopping.set()  # noqa: E731 - signal handler
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handler)
    with WorkerPool(
        runners=(checks.run_next, agent.run_next),
        size=config.worker_threads,
        poll_seconds=config.worker_poll_seconds,
    ):
        while not stopping.wait(timeout=config.job_lease_seconds / 2):
            sweep_once(config=config, checks=checks, agent=agent)


if __name__ == "__main__":
    worker_main()
