"""Use cases about engines."""

from __future__ import annotations

from app.domain.capabilities import CapabilityRow, capability_table
from app.domain.equivalence import EquivalenceClass, equivalence_table
from app.domain.models import EngineInfo

from .ports import EngineGateway


class EngineService:
    """Read the engine catalog: who is there, what each can check, who is interchangeable."""

    def __init__(self, *, engines: EngineGateway) -> None:
        """Create the service with its gateway."""
        self._engines = engines

    def list_engines(
        self, *, can_check: str | None = None, colored: bool | None = None
    ) -> tuple[EngineInfo, ...]:
        """Return the registered engines with their availability on this machine.

        ``can_check`` keeps the engines that check a class of properties (``ltl-fireability``),
        ``colored`` those that do (or do not) read colored nets.
        """
        return tuple(
            engine
            for engine in self._engines.list_engines()
            if (can_check is None or can_check in engine.classes)
            and (colored is None or engine.supports_colored == colored)
        )

    def capabilities(self) -> tuple[CapabilityRow, ...]:
        """Return, for every class of properties, the engines that can check it."""
        return capability_table(engines=self._engines.list_engines())

    def equivalence(self) -> tuple[EquivalenceClass, ...]:
        """Return, for every class, the engines that are interchangeable for it."""
        return equivalence_table(engines=self._engines.list_engines())
