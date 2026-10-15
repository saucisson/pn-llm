"""Use cases about nets."""

from __future__ import annotations

from app.domain.canonical import net_id_of
from app.domain.errors import PayloadTooLargeError
from app.domain.net_validation import DocumentLimits, parse_document
from app.domain.nets import NetFormat, NetSummary, SavedNet, StoredNet, summarize_document
from app.domain.pnml_export import render_pnml
from app.domain.pnml_import import import_pnml

from .ports import NetRepository


class NetService:
    """Register and read nets."""

    def __init__(
        self, *, nets: NetRepository, max_upload_bytes: int, limits: DocumentLimits
    ) -> None:
        """Create the service with its repository, the accepted upload size and the bounds."""
        self._nets = nets
        self._max_upload_bytes = max_upload_bytes
        self._limits = limits

    def register(self, *, payload: bytes, format: NetFormat) -> SavedNet:  # noqa: A002 - domain word
        """Convert an upload to the canonical document and store it.

        Registering the same net twice, in any format, is a no-op that returns the first one.

        Raises:
            PayloadTooLargeError: if the payload exceeds the configured size.
            InvalidNetError: if the payload is not a usable net.
        """
        if len(payload) > self._max_upload_bytes:
            raise PayloadTooLargeError(f"Upload larger than {self._max_upload_bytes} bytes")
        if format is NetFormat.PNML:
            document = import_pnml(payload=payload, limits=self._limits)
        else:
            document = parse_document(payload=payload, limits=self._limits)
        net_id = net_id_of(document=document)
        summary = summarize_document(document=document, net_id=net_id)
        return self._nets.save_net(summary=summary, document=document)

    def register_derived(self, *, payload: bytes, parent: NetSummary, rule: str) -> SavedNet:
        """Store a net produced from another by a reduction rule, linked to its parent.

        The same net derived twice (from the same or another parent) is stored once; the summary
        keeps the parent and the rules of the first derivation.

        Raises:
            PayloadTooLargeError, InvalidNetError: as for ``register``.
        """
        if len(payload) > self._max_upload_bytes:
            raise PayloadTooLargeError(f"Derived net larger than {self._max_upload_bytes} bytes")
        document = import_pnml(payload=payload, limits=self._limits)
        net_id = net_id_of(document=document)
        summary = summarize_document(document=document, net_id=net_id).model_copy(
            update={
                "parent_id": parent.net_id,
                "reductions_applied": (*parent.reductions_applied, rule),
            }
        )
        return self._nets.save_net(summary=summary, document=document)

    def get(self, *, net_id: str) -> StoredNet:
        """Return a stored net with its summary.

        Raises:
            NotFoundError: if the net is unknown.
        """
        return self._nets.load_net(net_id=net_id)

    def pnml(self, *, net_id: str) -> bytes:
        """Return the canonical PNML of a stored net.

        Raises:
            NotFoundError: if the net is unknown.
        """
        return render_pnml(document=self._nets.load_net(net_id=net_id).document)
