"""Use cases that delete user data, and the retention policy (ADR 0003, docs/architecture.md)."""

from __future__ import annotations

from app.domain.errors import ConflictError, NotFoundError

from .agent import AgentService
from .ports import DescriptionRepository, NetRepository, RetentionRepository


class RetentionService:
    """Delete sessions, nets and descriptions, and expire old ones."""

    def __init__(
        self,
        *,
        retention: RetentionRepository,
        agent: AgentService,
        nets: NetRepository,
        descriptions: DescriptionRepository,
    ) -> None:
        """Create the service over the repositories and the agent (to stop a run first)."""
        self._retention = retention
        self._agent = agent
        self._nets = nets
        self._descriptions = descriptions

    def delete_session(self, *, session_id: str) -> None:
        """Cancel a session if it is live, then delete it with its events.

        Raises:
            NotFoundError: if the session is unknown.
        """
        self._agent.cancel(session_id=session_id)  # raises NotFoundError, stops the run
        self._retention.delete_session(session_id=session_id)

    def delete_net(self, *, net_id: str, cascade: bool) -> None:
        """Delete a net.

        A net that jobs or sessions refer to is deleted only with ``cascade``, and never while
        one of them is queued or running: stop them first.

        Raises:
            NotFoundError: if the net is unknown.
            ConflictError: if it is in use and ``cascade`` is not set, or something is running.
        """
        self._nets.load_net(net_id=net_id)  # raises NotFoundError
        references = self._retention.references_of(net_id=net_id)
        if references.live:
            raise ConflictError(f"{references.live} job(s) or session(s) on this net are running")
        if (references.jobs or references.sessions) and not cascade:
            raise ConflictError(
                f"The net is used by {references.jobs} job(s) and "
                f"{references.sessions} session(s): delete them with cascade=true"
            )
        self._retention.delete_net(net_id=net_id)

    def delete_description(self, *, description_id: str, net_id: str) -> None:
        """Unlink a description from a net, deleting its text when nothing else uses it.

        Raises:
            NotFoundError: if the description is not linked to that net.
        """
        if not self._retention.delete_description_link(
            description_id=description_id, net_id=net_id
        ):
            raise NotFoundError("That description is not linked to that net")

    def expire(
        self, *, sessions_older_than_s: float | None, nets_older_than_s: float | None
    ) -> int:
        """Apply the retention policy; return how many sessions and nets were deleted."""
        count = 0
        if sessions_older_than_s is not None:
            count += self._retention.purge_sessions(older_than_s=sessions_older_than_s)
        if nets_older_than_s is not None:
            count += self._retention.purge_unreferenced(older_than_s=nets_older_than_s)
        return count
