"""Dummy engine following the entrypoint contract version 1 (docs/engine-contract.md).

Template for the real adapters and test of the Docker runner. Verifies nothing: answers UNKNOWN.
"""

import json
import time
from pathlib import Path

VERSION = "0.2"

inp = Path("/work/input")
out = Path("/work/output")

started = time.monotonic()
request = json.loads((inp / "request.json").read_text())
results = [
    {
        "id": formula["id"],
        "verdict": "UNKNOWN",
        "time_s": 0.0,
        "rendered": None,
        "trace": None,
        "warnings": ["dummy_engine_no_verification"],
    }
    for formula in request["formulas"]
]
envelope = {
    "schema_version": "1.0",
    "tool": {"name": "dummy-docker", "version": VERSION},
    "net_id": request["net_id"],
    "status": "ok",
    "data": {"results": results},
    "warnings": [],
    "truncated": None,
    "error": None,
    "elapsed_s": time.monotonic() - started,
}
(out / "result.json").write_text(json.dumps(envelope))
