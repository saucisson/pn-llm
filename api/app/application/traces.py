"""Use case: a counterexample on the original net, or on the reduced one it was found on."""

from __future__ import annotations

from typing import Literal

from app.domain.engine_contract import Trace
from app.domain.lifting import lift_trace
from app.domain.net_structure import build_structure
from app.domain.operations import Lineage

from .checks import CheckService
from .ports import NetRepository, OperationRepository

TraceView = Literal["original", "reduced"]


class TraceService:
    """Read counterexamples, lifting them to the original net of a chain of reductions."""

    def __init__(
        self, *, checks: CheckService, nets: NetRepository, lineage: OperationRepository
    ) -> None:
        """Create the service over the check service, the nets and the lineage store."""
        self._checks = checks
        self._nets = nets
        self._lineage = lineage

    def get(self, *, job_id: str, result_index: int, view: TraceView) -> Trace:
        """Return the counterexample of a result, on the original net unless ``view`` says not.

        A job on an uploaded net has nothing to lift. A net reduced several times is lifted
        through each reduction in turn (the first derivation, if it has been derived more than
        one way).

        Raises:
            NotFoundError: if the job, the result or its trace does not exist.
            InvalidRequestError: if the lifted trace does not fit the original net.
        """
        trace = self._checks.trace(job_id=job_id, result_index=result_index)
        if view == "reduced":
            return trace
        chain: list[Lineage] = []
        current = trace.net_id
        while links := self._lineage.lineage_of(net_id=current):
            chain.append(links[0])
            current = links[0].parent_id
        if not chain:
            return trace
        root = build_structure(
            document=self._nets.load_net(net_id=current).document, net_id=current
        )
        return lift_trace(trace=trace, chain=tuple(chain), root=root)
