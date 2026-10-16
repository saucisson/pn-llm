"""Contest families and instances in the SQLite database."""

from __future__ import annotations

import zlib
from collections.abc import Iterable

from app.domain.errors import NotFoundError
from app.domain.mcc import MccFamily, MccNetType, ModelEntry
from app.domain.mcc_properties import Examination, MccProperties
from app.domain.predictor import InstanceSize

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

    def save_properties(self, *, net_id: str, properties: MccProperties) -> None:
        """Store the properties of an examination for a net, replacing the previous ones."""
        body = zlib.compress(properties.model_dump_json().encode())
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mcc_properties(net_id, examination, body) VALUES (?, ?, ?)",
                (net_id, properties.examination, body),
            )

    def properties_of(self, *, net_id: str, examination: Examination) -> MccProperties:
        """Return the properties of an examination for a net, or raise NotFoundError."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT body FROM mcc_properties WHERE net_id=? AND examination=?",
                (net_id, examination),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"No {examination} properties for net {net_id}")
        return MccProperties.model_validate_json(zlib.decompress(row["body"]))

    def save_sizes(self, *, sizes: Iterable[InstanceSize]) -> int:
        """Store the sizes of contest instances, replacing earlier ones; return how many."""
        count = 0
        with self._connection() as conn:
            for size in sizes:
                conn.execute(
                    "INSERT OR REPLACE INTO mcc_instance_sizes VALUES (?,?,?,?,?,?)",
                    (
                        size.instance,
                        size.family,
                        size.net_type.value,
                        size.places,
                        size.transitions,
                        size.arcs,
                    ),
                )
                count += 1
        return count

    def sizes(self) -> tuple[InstanceSize, ...]:
        """Return the stored instance sizes, by instance."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM mcc_instance_sizes ORDER BY instance").fetchall()
        return tuple(InstanceSize.model_validate(dict(row)) for row in rows)
