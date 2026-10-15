"""Helpers shared by the engine adapters (docs/engine-integration-checklist.md)."""

from .adapter import (
    AdapterAnswer,
    AdapterInput,
    OperationAnswer,
    normalize_verdict,
    read_request,
    run_adapter,
    write_failure,
    write_result,
)

__all__ = [
    "AdapterAnswer",
    "AdapterInput",
    "OperationAnswer",
    "normalize_verdict",
    "read_request",
    "run_adapter",
    "write_failure",
    "write_result",
]
