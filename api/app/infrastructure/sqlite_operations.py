"""Runs of operations in the SQLite database: a queue claimed atomically, and the result cache."""

from __future__ import annotations

import sqlite3
import time

from pydantic import JsonValue, TypeAdapter

from app.domain.errors import NotFoundError
from app.domain.models import Limits
from app.domain.operations import OperationOutcome, OperationRun, RunState, RunSubmission

from .sqlite_database import SqliteDatabase

JSON = TypeAdapter(JsonValue)


def run_from_row(*, row: sqlite3.Row) -> OperationRun:
    """Rebuild a run from its row."""
    return OperationRun(
        run_id=row["run_id"],
        net_id=row["net_id"],
        operation=row["operation"],
        engine=row["engine"],
        tool_version=row["tool_version"],
        parameters=JSON.validate_json(row["parameters"]),
        limits=Limits.model_validate_json(row["limits"]),
        state=RunState(row["state"]),
        outcome=None
        if row["outcome"] is None
        else OperationOutcome.model_validate_json(row["outcome"]),
    )


class SqliteOperations(SqliteDatabase):
    """Implements the ``OperationRepository`` port."""

    def create_or_get_run(self, *, run: OperationRun, key: str) -> RunSubmission:
        """Insert ``run`` unless a queued, running or finished run has the same key.

        Safe under concurrent calls thanks to the unique index on live keys.
        """
        now = time.time()
        while True:
            try:
                with self._connection() as conn:
                    conn.execute(
                        "INSERT INTO operation_runs(run_id, net_id, operation, engine,"
                        " tool_version, run_key, parameters, limits, state, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run.run_id,
                            run.net_id,
                            run.operation,
                            run.engine,
                            run.tool_version,
                            key,
                            JSON.dump_json(run.parameters).decode(),
                            run.limits.model_dump_json(),
                            run.state.value,
                            now,
                            now,
                        ),
                    )
                return RunSubmission(run=run, created=True)
            except sqlite3.IntegrityError:
                with self._connection() as conn:
                    row = conn.execute(
                        "SELECT * FROM operation_runs WHERE run_key=?"
                        " AND state IN ('queued','running','done')"
                        " ORDER BY created_at DESC LIMIT 1",
                        (key,),
                    ).fetchone()
                if row is not None:
                    return RunSubmission(run=run_from_row(row=row), created=False)
                # The live run ended between the two statements: try again.

    def load_run(self, *, run_id: str) -> OperationRun:
        """Return a run, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM operation_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown run: {run_id}")
        return run_from_row(row=row)

    def claim_next_run(self, *, lease_seconds: float) -> OperationRun | None:
        """Atomically claim the oldest queued run, or None if none waits."""
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "UPDATE operation_runs SET state='running', lease_expires_at=?, updated_at=?"
                " WHERE run_id = (SELECT run_id FROM operation_runs WHERE state='queued'"
                " ORDER BY created_at, run_id LIMIT 1) AND state='queued' RETURNING run_id",
                (now + lease_seconds, now),
            ).fetchone()
        return None if row is None else self.load_run(run_id=row["run_id"])

    def renew_lease(self, *, run_id: str, lease_seconds: float) -> bool:
        """Extend the lease of a running run; False if it is no longer running."""
        now = time.time()
        with self._connection() as conn:
            return (
                conn.execute(
                    "UPDATE operation_runs SET lease_expires_at=?, updated_at=?"
                    " WHERE run_id=? AND state='running'",
                    (now + lease_seconds, now, run_id),
                ).rowcount
                == 1
            )

    def finish_run(self, *, run_id: str, outcome: OperationOutcome) -> None:
        """Store the outcome and end the run, only if it is still running."""
        state = RunState.DONE if outcome.status == "ok" else RunState.FAILED
        with self._connection() as conn:
            conn.execute(
                "UPDATE operation_runs SET outcome=?, state=?, updated_at=?"
                " WHERE run_id=? AND state='running'",
                (outcome.model_dump_json(), state.value, time.time(), run_id),
            )

    def cancel_run(self, *, run_id: str) -> None:
        """Cancel a queued or running run; finished runs keep their state."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE operation_runs SET state='cancelled', updated_at=?"
                " WHERE run_id=? AND state IN ('queued','running')",
                (time.time(), run_id),
            )

    def recover_interrupted_runs(self) -> int:
        """Mark running runs whose lease expired as interrupted; safe from any process."""
        now = time.time()
        with self._connection() as conn:
            return conn.execute(
                "UPDATE operation_runs SET state='interrupted', updated_at=?"
                " WHERE state='running' AND lease_expires_at < ?",
                (now, now),
            ).rowcount

    def purge_finished_runs(self, *, older_than_s: float) -> int:
        """Delete finished runs not touched for ``older_than_s`` seconds."""
        with self._connection() as conn:
            return conn.execute(
                "DELETE FROM operation_runs WHERE state IN ('done','failed','cancelled',"
                "'interrupted') AND updated_at < ?",
                (time.time() - older_than_s,),
            ).rowcount
