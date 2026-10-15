"""Application settings, read from ``PNVERIF_*`` environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.net_validation import DocumentLimits

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
    # How long a request for an analysis waits for the answer before replying 202 with a run.
    operation_wait_seconds: float = 5.0
    # Directory of the built UI (ui/dist), served under /ui; None or a missing directory: no UI.
    ui_dir: Path | None = None
    # Worker threads started inside each API process; 0 for an API process that only enqueues
    # (workers then run elsewhere: ``python -m app.main``).
    embedded_workers: int = 2
    # How long an idle worker waits before looking at the queue again.
    worker_poll_seconds: float = 0.5
    # Worker threads of ``python -m app.main``.
    worker_threads: int = 2
    # Largest accepted description of a net (UTF-8 bytes).
    max_description_bytes: int = 65_536

    # Model Checking Contest data (``python -m app.seed``): where downloads are kept, where they
    # come from, and the largest net accepted when seeding (contest nets can be huge).
    mcc_directory: Path = Path("data/mcc")
    mcc_year: int = 2026
    mcc_base_url: str = "https://mcc.lip6.fr/2026"
    mcc_max_net_bytes: int = 512 * 1024 * 1024

    # The language model behind the chat: "none" (sessions end with an explanatory error),
    # "scripted" (an offline demonstration, no key) or "anthropic".
    llm_provider: Literal["none", "scripted", "anthropic"] = "none"
    # Budgets of one agent run.
    agent_max_steps: int = 40
    agent_max_tool_calls: int = 80
    agent_max_tokens: int = 400_000
    agent_max_seconds: float = 900.0
    # Largest answer of a tool, in characters; a bigger one is refused with advice.
    tool_result_max_chars: int = 16_000
    # How often a check waits for its engine to answer.
    tool_poll_seconds: float = 0.2
    # A session waiting for the user for this many days is cancelled; None waits for ever.
    session_waiting_expiry_days: float | None = 7.0

    # The Anthropic provider: the key (PNVERIF_ANTHROPIC_API_KEY, or the usual ANTHROPIC_API_KEY),
    # the model and the largest answer of one step. The key is never logged nor put in events.
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("PNVERIF_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    anthropic_model: str = "claude-opus-4-8"
    anthropic_max_tokens: int = 8_000

    # Logs go to standard error, one JSON object per line unless PNVERIF_LOG_JSON is false.
    log_level: str = "INFO"
    log_json: bool = True

    # Retention of user data, in days (None keeps it for ever). Sessions not touched for this long
    # are deleted with their events; nets that no job or session uses, and descriptions no net
    # links to, are deleted after the second delay.
    session_retention_days: float | None = None
    unreferenced_net_retention_days: float | None = None

    def document_limits(self) -> DocumentLimits:
        """Return the bounds applied to every net entering the platform."""
        return DocumentLimits(
            max_elements=self.max_net_elements,
            max_page_depth=self.max_page_depth,
            max_xml_depth=self.max_xml_depth,
            max_string_length=self.max_string_length,
        )
