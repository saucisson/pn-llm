"""The native engine: the platform's own analyses, run in a container like any other engine.

The algorithms live in ``app.domain.analyses`` (unit-tested there); this adapter only reads the
net, finds the operation the request names and writes its result. Running them in a container
gives them the same limits as every engine: a memory bound and a timeout that kills.
Bump ``TOOL_VERSION`` in the Dockerfile and the registry whenever an algorithm changes, because
results are cached by tool version.
"""

import os

from pnverif_engine import AdapterInput, OperationAnswer, run_adapter

from app.domain.net_validation import DocumentLimits
from app.domain.perform import perform
from app.domain.pnml_export import render_pnml
from app.domain.pnml_import import import_pnml

TOOL_NAME = "native"
TOOL_VERSION = os.environ["TOOL_VERSION"]


def operate(given: AdapterInput) -> OperationAnswer:  # noqa: PLR0917 - callback of run_adapter
    """Run the operation the request names on the net and return its result (and reduced net)."""
    request = given.request
    document = import_pnml(payload=given.net_path.read_bytes(), limits=DocumentLimits())
    performed = perform(
        operation=request.operation or "",
        document=document,
        net_id=request.net_id,
        parameters=request.parameters,
    )
    return OperationAnswer(
        result=performed.result,
        reduced_pnml=None if performed.reduced is None else render_pnml(document=performed.reduced),
    )


if __name__ == "__main__":
    run_adapter(tool_name=TOOL_NAME, tool_version=TOOL_VERSION, operate=operate)
