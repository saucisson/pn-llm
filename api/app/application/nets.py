"""Use cases about nets."""

from __future__ import annotations

from app.domain import pnml
from app.domain.errors import PayloadTooLargeError
from app.domain.models import NetSummary

from .ports import NetRepository


class NetService:
    """Register and read nets."""

    def __init__(self, *, nets: NetRepository, max_pnml_bytes: int) -> None:
        """Create the service with its repository and the accepted payload size."""
        self._nets = nets
        self._max_pnml_bytes = max_pnml_bytes

    def register(self, *, payload: bytes) -> NetSummary:
        """Validate a PNML payload and store it. Registering the same content twice is a no-op.

        Raises:
            PayloadTooLargeError: if the payload exceeds the configured size.
            PnmlError: if the payload is not a usable net.
        """
        if len(payload) > self._max_pnml_bytes:
            raise PayloadTooLargeError(f"PNML larger than {self._max_pnml_bytes} bytes")
        stored = self._nets.save_net(summary=pnml.summarize(pnml=payload), pnml=payload)
        return stored.summary

    def get(self, *, net_id: str) -> NetSummary:
        """Return the summary of a stored net.

        Raises:
            NotFoundError: if the net is unknown.
        """
        return self._nets.load_net(net_id=net_id).summary
