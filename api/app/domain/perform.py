"""Perform an operation on a net document: the one place that knows what a reduction also yields."""

from __future__ import annotations

from pydantic import JsonValue

from .catalog import find_operation
from .errors import InvalidRequestError
from .models import DomainModel
from .net_document import NetDocument
from .net_structure import build_structure
from .operations import compute_on
from .reductions.document import structure_to_document
from .reductions.result import DocumentComputation, ReductionComputation


class Performed(DomainModel):
    """What performing an operation produced: its result as JSON and, for a reduction, the net."""

    result: JsonValue
    reduced: NetDocument | None = None


def perform(
    *, operation: str, document: NetDocument, net_id: str, parameters: JsonValue
) -> Performed:
    """Run a named operation on a document.

    Raises:
        InvalidRequestError: if the operation is unknown.
    """
    definition = find_operation(name=operation)
    if definition is None:
        raise InvalidRequestError(f"unknown operation {operation!r}")
    computed = compute_on(
        definition=definition,
        structure=build_structure(document=document, net_id=net_id),
        parameters=parameters,
        document=document,
    )
    if isinstance(computed, DocumentComputation):
        return Performed(result=computed.result.model_dump(mode="json"), reduced=computed.document)
    if isinstance(computed, ReductionComputation):
        return Performed(
            result=computed.result.model_dump(mode="json"),
            reduced=(
                None
                if computed.reduced is None
                else structure_to_document(structure=computed.reduced, source_id=document.source_id)
            ),
        )
    return Performed(result=computed.model_dump(mode="json"))
