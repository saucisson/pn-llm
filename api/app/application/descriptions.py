"""Use cases about net descriptions (ADR 0011)."""

from __future__ import annotations

from app.domain.descriptions import Description, DescriptionOrigin, SavedDescription
from app.domain.errors import InvalidRequestError, PayloadTooLargeError

from .ports import DescriptionRepository, NetRepository


class DescriptionService:
    """Add and read the descriptions of nets."""

    def __init__(
        self, *, nets: NetRepository, descriptions: DescriptionRepository, max_bytes: int
    ) -> None:
        """Create the service with its repositories and the largest accepted text."""
        self._nets = nets
        self._descriptions = descriptions
        self._max_bytes = max_bytes

    def add(self, *, net_id: str, payload: bytes, origin: DescriptionOrigin) -> SavedDescription:
        """Store a description exactly as sent and link it to a net. Idempotent.

        Raises:
            NotFoundError: if the net is unknown.
            PayloadTooLargeError: if the text exceeds the configured size.
            InvalidRequestError: if the text is empty or is not valid UTF-8.
        """
        self._nets.load_net(net_id=net_id)  # raises NotFoundError
        if len(payload) > self._max_bytes:
            raise PayloadTooLargeError(f"Description larger than {self._max_bytes} bytes")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidRequestError("A description must be UTF-8 text") from exc
        if not text.strip():
            raise InvalidRequestError("A description cannot be empty")
        return self._descriptions.save_description(net_id=net_id, text=text, origin=origin)

    def of_net(self, *, net_id: str) -> tuple[Description, ...]:
        """Return the descriptions linked to a net.

        Raises:
            NotFoundError: if the net is unknown.
        """
        self._nets.load_net(net_id=net_id)
        return self._descriptions.descriptions_of(net_id=net_id)

    def get(self, *, description_id: str) -> tuple[Description, ...]:
        """Return a description with each of its links to nets.

        Raises:
            NotFoundError: if the description is unknown.
        """
        return self._descriptions.load_description(description_id=description_id)
