"""Dummy engine following the entrypoint contract (docs/engine-contract.md).

Template for the real adapters and test of the Docker runner. Verifies nothing: answers UNKNOWN.
"""

import json
from pathlib import Path

inp = Path("/work/input")
out = Path("/work/output")

request = json.loads((inp / "request.json").read_text())
results = [
    {
        "id": f["id"],
        "verdict": "UNKNOWN",
        "engine": "dummy-docker",
        "engine_version": "0.1",
        "time_s": 0.0,
        "warnings": ["dummy_engine_no_verification"],
    }
    for f in request["formulas"]
]
(out / "result.json").write_text(json.dumps({"results": results}))
