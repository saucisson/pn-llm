"""Shared fixtures and test data."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.sqlite_store import SqliteStore
from app.main import create_app
from app.settings import Settings

from .support import MUTEX_PNML, ScriptedEngines


@pytest.fixture
def mutex_pnml() -> bytes:
    return MUTEX_PNML


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_path=tmp_path / "test.sqlite")


@pytest.fixture
def store(settings: Settings) -> SqliteStore:
    return SqliteStore(path=settings.database_path)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings))


@pytest.fixture
def scripted_client(settings: Settings) -> TestClient:
    """A client whose engine answers FALSE with the counterexample enter1 (see ScriptedEngines)."""
    return TestClient(create_app(settings=settings, engine_gateway=ScriptedEngines()))
