"""Application settings, read from ``PNVERIF_*`` environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_JOB_LEASE_SECONDS = 60.0


class Settings(BaseSettings):
    """Immutable configuration. Example: ``PNVERIF_DATABASE_PATH=/data/pnverif.sqlite``."""

    model_config = SettingsConfigDict(env_prefix="PNVERIF_", frozen=True)

    database_path: Path = Path("data/pnverif.sqlite")
    # Largest accepted upload, in either format (JSON net document or PNML).
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_net_elements: int = 5_000_000
    max_page_depth: int = 32
    max_xml_depth: int = 64
    max_string_length: int = 65_536
    # A running job whose owner has not renewed its lease for this long is marked interrupted.
    # Renewals happen three times per lease, so one missed beat is tolerated.
    job_lease_seconds: float = DEFAULT_JOB_LEASE_SECONDS
    # Finished jobs (and their counterexamples) older than this many days are deleted; None keeps
    # them for ever. Nets are never deleted.
    job_retention_days: float | None = None
    # Directory of the built UI (ui/dist), served under /ui; None or a missing directory: no UI.
    ui_dir: Path | None = None
