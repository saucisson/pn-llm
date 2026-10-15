"""Deletion of user data in the SQLite database (docs/architecture.md, "Retention and deletion").

Nets and descriptions are shared by content: the same net or text uploaded twice is one record. So
data is deleted along its references, never blindly: a net goes with what depends on it, a text
goes when no net links to it.
"""

from __future__ import annotations

import time

from app.domain.nets import NetReferences

from .sqlite_database import SqliteDatabase


class SqliteRetention(SqliteDatabase):
    """Implements the ``RetentionRepository`` port."""

    def delete_session(self, *, session_id: str) -> bool:
        """Delete a session and its events; False if it did not exist."""
        with self._connection() as conn:
            conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            return (
                conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,)).rowcount == 1
            )

    def purge_sessions(self, *, older_than_s: float) -> int:
        """Delete the sessions not touched for this long, unless a run is queued or running."""
        cutoff = time.time() - older_than_s
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM events WHERE session_id IN (SELECT session_id FROM sessions"
                " WHERE updated_at < ? AND state NOT IN ('queued','running'))",
                (cutoff,),
            )
            return conn.execute(
                "DELETE FROM sessions WHERE updated_at < ? AND state NOT IN ('queued','running')",
                (cutoff,),
            ).rowcount

    def references_of(self, *, net_id: str) -> NetReferences:
        """Return how many jobs and sessions refer to a net, and how many of them are live."""
        with self._connection() as conn:
            jobs, live_jobs = conn.execute(
                "SELECT count(*), coalesce(sum(state IN ('queued','running')), 0) FROM jobs"
                " WHERE net_id=?",
                (net_id,),
            ).fetchone()
            sessions, live_sessions = conn.execute(
                "SELECT count(*), coalesce(sum(state IN ('queued','running')), 0) FROM sessions"
                " WHERE net_id=?",
                (net_id,),
            ).fetchone()
        return NetReferences(jobs=jobs, sessions=sessions, live=live_jobs + live_sessions)

    def delete_net(self, *, net_id: str) -> bool:
        """Delete a net with its jobs, runs, traces, sessions, events, links and contest records."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM traces WHERE job_id IN (SELECT job_id FROM jobs WHERE net_id=?)",
                (net_id,),
            )
            conn.execute("DELETE FROM jobs WHERE net_id=?", (net_id,))
            conn.execute("DELETE FROM operation_runs WHERE net_id=?", (net_id,))
            conn.execute("DELETE FROM net_lineage WHERE net_id=? OR parent_id=?", (net_id, net_id))
            conn.execute("DELETE FROM mcc_nets WHERE net_id=?", (net_id,))
            conn.execute("DELETE FROM mcc_properties WHERE net_id=?", (net_id,))
            conn.execute(
                "DELETE FROM events WHERE session_id IN"
                " (SELECT session_id FROM sessions WHERE net_id=?)",
                (net_id,),
            )
            conn.execute("DELETE FROM sessions WHERE net_id=?", (net_id,))
            conn.execute("DELETE FROM net_descriptions WHERE net_id=?", (net_id,))
            deleted = conn.execute("DELETE FROM nets WHERE net_id=?", (net_id,)).rowcount == 1
            conn.execute(
                "DELETE FROM descriptions WHERE description_id NOT IN"
                " (SELECT description_id FROM net_descriptions)"
            )
        return deleted

    def delete_description_link(self, *, description_id: str, net_id: str) -> bool:
        """Unlink a description from a net; the text goes when no net uses it any more."""
        with self._connection() as conn:
            unlinked = (
                conn.execute(
                    "DELETE FROM net_descriptions WHERE description_id=? AND net_id=?",
                    (description_id, net_id),
                ).rowcount
                > 0
            )
            conn.execute(
                "DELETE FROM descriptions WHERE description_id NOT IN"
                " (SELECT description_id FROM net_descriptions)"
            )
        return unlinked

    def purge_unreferenced(self, *, older_than_s: float) -> int:
        """Delete nets older than this that no job or session uses, and unlinked descriptions."""
        cutoff = time.time() - older_than_s
        with self._connection() as conn:
            conn.execute(
                "WITH unused AS (SELECT net_id FROM nets WHERE created_at < ?"
                " AND net_id NOT IN (SELECT net_id FROM jobs)"
                " AND net_id NOT IN (SELECT net_id FROM sessions))"
                " DELETE FROM net_descriptions WHERE net_id IN (SELECT net_id FROM unused)",
                (cutoff,),
            )
            conn.execute(
                "WITH unused AS (SELECT net_id FROM nets WHERE created_at < ?"
                " AND net_id NOT IN (SELECT net_id FROM jobs)"
                " AND net_id NOT IN (SELECT net_id FROM sessions))"
                " DELETE FROM nets WHERE net_id IN (SELECT net_id FROM unused)",
                (cutoff,),
            )
            # A DELETE with a WITH clause does not report its row count: ask SQLite.
            deleted = int(conn.execute("SELECT changes()").fetchone()[0])
            conn.execute(
                "DELETE FROM descriptions WHERE description_id NOT IN"
                " (SELECT description_id FROM net_descriptions)"
            )
        return deleted
