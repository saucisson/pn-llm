import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain.contract import (
    Bound,
    ElementRef,
    Envelope,
    ErrorInfo,
    FiniteBound,
    Marking,
    MarkingEntry,
    Page,
    PageRequest,
    ToolInfo,
    UnboundedBound,
)

TOOL = ToolInfo(name="analysis.test", version="1.0")


def place(*, place_id: str) -> ElementRef:
    return ElementRef(id=place_id, name=f"name of {place_id}", kind="place")


def test_marking_is_sorted_by_place_id():
    marking = Marking(
        entries=(
            MarkingEntry(place=place(place_id="p2"), tokens=1),
            MarkingEntry(place=place(place_id="p1"), tokens=3),
        )
    )
    assert [entry.place.id for entry in marking.entries] == ["p1", "p2"]


def test_marking_is_sparse():
    with pytest.raises(ValidationError):
        MarkingEntry(place=place(place_id="p1"), tokens=0)


@pytest.mark.parametrize(
    "document",
    [{"kind": "finite", "value": 1}, {"kind": "unbounded"}, {"kind": "unknown"}],
)
def test_bound_round_trips_through_json(document):
    adapter = TypeAdapter(Bound)
    bound = adapter.validate_python(document)
    assert adapter.dump_python(bound) == document


def test_bound_rejects_a_negative_value_and_an_unknown_kind():
    with pytest.raises(ValidationError):
        FiniteBound(value=-1)
    with pytest.raises(ValidationError):
        TypeAdapter(Bound).validate_python({"kind": "maybe"})
    assert UnboundedBound().kind == "unbounded"


def test_page_request_is_bounded():
    assert PageRequest().limit == 50
    with pytest.raises(ValidationError):
        PageRequest(limit=501)
    with pytest.raises(ValidationError):
        PageRequest(limit=0)


def test_ok_envelope_round_trips_and_names_its_tool():
    envelope = Envelope[tuple[ElementRef, ...]](
        tool=TOOL,
        net_id="n1",
        status="ok",
        data=(place(place_id="p1"),),
        truncated=Page(returned=1, total=5, next_cursor="c"),
        elapsed_s=0.1,
    )
    parsed = Envelope[tuple[ElementRef, ...]].model_validate_json(envelope.model_dump_json())
    assert parsed == envelope
    assert parsed.schema_version == "1.0"


def test_failed_envelope_has_an_error_and_no_data():
    failed = Envelope[int](
        tool=TOOL, status="failed", error=ErrorInfo(code="timeout", message="too slow"), elapsed_s=1
    )
    assert failed.data is None


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "failed"},
        {"status": "failed", "data": 1, "error": ErrorInfo(code="x", message="y")},
        {"status": "ok"},
        {"status": "partial", "data": 1, "error": ErrorInfo(code="x", message="y")},
    ],
)
def test_an_envelope_cannot_contradict_its_status(fields):
    with pytest.raises(ValidationError):
        Envelope[int](tool=TOOL, elapsed_s=0, **fields)
