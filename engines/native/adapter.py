"""The native engine: the platform's own analyses, run in a container like any other engine.

The algorithms live in ``app.domain.analyses`` (unit-tested there); this adapter only reads the
net, finds the operation the request names and writes its result. Running them in a container
gives them the same limits as every engine: a memory bound and a timeout that kills.
Bump ``TOOL_VERSION`` in the Dockerfile and the registry whenever an algorithm changes, because
results are cached by tool version.
"""

import os

from pnverif_engine import AdapterInput, OperationAnswer, run_adapter

from app.domain.analyses import find_operation
from app.domain.net_structure import build_structure
from app.domain.net_validation import DocumentLimits
from app.domain.operations import compute_on
from app.domain.pnml_import import import_pnml

TOOL_NAME = "native"
TOOL_VERSION = os.environ["TOOL_VERSION"]


def operate(given: AdapterInput) -> OperationAnswer:  # noqa: PLR0917 - callback of run_adapter
    """Run the operation the request names on the net and return its result."""
    request = given.request
    definition = find_operation(name=request.operation or "")
    if definition is None:
        message = f"unknown operation {request.operation!r}"
        raise ValueError(message)
    document = import_pnml(payload=given.net_path.read_bytes(), limits=DocumentLimits())
    structure = build_structure(document=document, net_id=request.net_id)
    result = compute_on(definition=definition, structure=structure, parameters=request.parameters)
    return OperationAnswer(result=result.model_dump(mode="json"))


if __name__ == "__main__":
    run_adapter(tool_name=TOOL_NAME, tool_version=TOOL_VERSION, operate=operate)
