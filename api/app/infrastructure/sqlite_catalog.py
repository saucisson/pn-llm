"""Contest families and instances in the SQLite database."""

from __future__ import annotations

from app.domain.mcc import MccFamily, MccNetType, ModelEntry

from .sqlite_database import SqliteDatabase


class SqliteCatalog(SqliteDatabase):
    """Implements the ``ModelCatalogRepository`` port."""

    def save_family(self, *, family: MccFamily) -> None:
        """Store a family, replacing the previous record of the same name."""
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mcc_families(name, family) VALUES (?, ?)",
                (family.name, family.model_dump_json()),
            )

    def save_entry(self, *, entry: ModelEntry) -> None:
        """Link a stored net to its family and instance; saving the same link twice is a no-op."""
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mcc_nets(family, instance, net_type, net_id, member)"
                " VALUES (?, ?, ?, ?, ?)",
                (entry.family, entry.instance, entry.net_type, entry.net_id, entry.member),
            )

    def families(self) -> tuple[MccFamily, ...]:
        """Return the stored families, by name."""
        with self._connection() as conn:
            rows = conn.execute("SELECT family FROM mcc_families ORDER BY name").fetchall()
        return tuple(MccFamily.model_validate_json(row["family"]) for row in rows)

    def entries(self, *, family: str | None, net_type: MccNetType | None) -> tuple[ModelEntry, ...]:
        """Return the entries matching the filters, by family then instance."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT family, instance, net_type, net_id, member FROM mcc_nets"
                " WHERE (? IS NULL OR family=?) AND (? IS NULL OR net_type=?)"
                " ORDER BY family, instance, net_type",
                (family, family, net_type, net_type),
            ).fetchall()
        return tuple(ModelEntry.model_validate(dict(row)) for row in rows)
