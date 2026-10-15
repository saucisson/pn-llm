"""Use cases about engines."""

from __future__ import annotations

from app.domain.models import EngineInfo

from .ports import EngineGateway


class EngineService:
    """Read the engine catalog."""

    def __init__(self, *, engines: EngineGateway) -> None:
        """Create the service with its gateway."""
        self._engines = engines

    def list_engines(self) -> tuple[EngineInfo, ...]:
        """Return the registered engines with their availability on this machine."""
        return self._engines.list_engines()
