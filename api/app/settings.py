"""Application settings, read from ``PNVERIF_*`` environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MAX_PNML_BYTES = 20 * 1024 * 1024
DEFAULT_JOB_LEASE_SECONDS = 60.0


class Settings(BaseSettings):
    """Immutable configuration. Example: ``PNVERIF_DATABASE_PATH=/data/pnverif.sqlite``."""

    model_config = SettingsConfigDict(env_prefix="PNVERIF_", frozen=True)

    database_path: Path = Path("data/pnverif.sqlite")
    max_pnml_bytes: int = DEFAULT_MAX_PNML_BYTES
    # A running job whose owner has not renewed its lease for this long is marked interrupted.
    # Renewals happen three times per lease, so one missed beat is tolerated.
    job_lease_seconds: float = DEFAULT_JOB_LEASE_SECONDS
