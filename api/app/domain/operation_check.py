"""Checking what an engine says an operation found, before it becomes a result of the platform.

An engine is a tool, not an authority: its result must have the shape the operation promises and
may cite only elements that exist in the net, with the names they have there.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, ValidationError

from .contract import ElementRef, ErrorInfo, ToolInfo
from .engine_contract import EngineOperationReport
from .net_structure import NetStructure
from .operations import OperationDefinition, OperationOutcome


def element_refs_in(*, value: object) -> Iterator[ElementRef]:
    """Yield every element reference in a result, however deep."""
    if isinstance(value, ElementRef):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from element_refs_in(value=getattr(value, name))
    elif isinstance(value, tuple | list):
        for item in value:
            yield from element_refs_in(value=item)


def interpret_operation_report(
    *,
    report: EngineOperationReport,
    definition: OperationDefinition,
    engine: str,
    engine_version: str,
    structure: NetStructure,
) -> OperationOutcome:
    """Turn what an engine produced into the outcome of the run, or into a failure."""
    tool = ToolInfo(name=report.tool_name or engine, version=report.tool_version or engine_version)

    def failed(*, code: str, message: str) -> OperationOutcome:
        return OperationOutcome(
            status="failed",
            tool=tool,
            error=ErrorInfo(code=code, message=message),
            warnings=report.warnings,
            elapsed_s=report.elapsed_s,
        )

    if report.status == "failed" or report.result is None:
        code = report.error_code or "no_result"
        return failed(code=code, message=f"The engine gave no result ({code})")
    try:
        result = definition.result_model.model_validate(report.result)
    except ValidationError as exc:
        return failed(
            code="invalid_result",
            message=f"Not a {definition.name} result: {exc.errors()[0]['msg']}",
        )
    nodes = {node.id: node for node in (*structure.places, *structure.transitions)}
    for ref in element_refs_in(value=result):
        node = nodes.get(ref.id)
        if node is None or node.kind != ref.kind or node.name != ref.name:
            return failed(
                code="result_cites_unknown_element",
                message=f"The result cites {ref.id!r}, which is not that element of the net",
            )
    warnings = report.warnings
    if report.tool_version is not None and report.tool_version != engine_version:
        warnings = (*warnings, f"tool_version_differs_from_registry:{report.tool_version}")
    return OperationOutcome(
        status="ok",
        tool=tool,
        result=result.model_dump(mode="json"),
        warnings=warnings,
        elapsed_s=report.elapsed_s,
    )
