import time

import pytest

from app.application.inspection import InspectionService
from app.domain.contract import PageRequest
from app.domain.errors import InvalidRequestError, NotFoundError
from app.domain.inspection import name_groups, neighbourhood, size_category
from app.domain.net_document import (
    PTNET_TYPE_URI,
    Annotation,
    Arc,
    NetDocument,
    Page,
    Place,
    RefPlace,
    Transition,
)
from app.domain.net_structure import build_structure
from app.domain.pagination import decode_cursor, encode_cursor, paginate


def named(*, place_id, name):
    return Place(id=place_id, name=Annotation(text=name))


def structure_of(*, places, transitions=(), arcs=(), kind_uri=PTNET_TYPE_URI, pages=()):
    document = NetDocument(
        source_id="n",
        type_uri=kind_uri,
        places=tuple(places),
        transitions=tuple(transitions),
        arcs=tuple(arcs),
        pages=tuple(pages),
    )
    return build_structure(document=document, net_id="x")


def test_cursor_round_trips_and_rejects_garbage():
    assert decode_cursor(cursor=encode_cursor(offset=42)) == 42
    for bad in ("!!!", "zzzz", encode_cursor(offset=1)[:-2] + "~"):
        with pytest.raises(InvalidRequestError):
            decode_cursor(cursor=bad)


def test_pagination_walks_a_list_exactly_once():
    items = tuple(range(25))
    seen = []
    cursor = None
    while True:
        page = paginate(items=items, request=PageRequest(limit=10, cursor=cursor))
        seen += page.items
        cursor = page.page.next_cursor
        if cursor is None:
            break
    assert tuple(seen) == items


def test_reference_nodes_are_resolved_in_arcs():
    page_a = Page(id="a", places=(Place(id="p"),))
    page_b = Page(
        id="b",
        transitions=(Transition(id="t"),),
        ref_places=(RefPlace(id="rp", ref="p"),),
        arcs=(Arc(id="x", source="rp", target="t"),),
    )
    structure = structure_of(places=(), pages=(page_a, page_b))
    assert [(a.source, a.target) for a in structure.arcs] == [("p", "t")]
    assert structure.has_reference_nodes is True


def test_name_groups_with_several_indices_and_padding():
    places = [
        named(place_id=f"c{i}{j}", name=f"cell_{i}_{j:02d}") for i in (1, 2) for j in (3, 5, 7)
    ]
    groups = name_groups(structure=structure_of(places=places), min_count=2)
    assert len(groups) == 1
    group = groups[0]
    assert group.pattern == "cell_{}_{}"
    assert group.count == 6
    assert (group.indices[0].min, group.indices[0].max, group.indices[0].distinct) == (1, 2, 2)
    assert group.indices[1].width == 2
    assert (group.indices[1].min, group.indices[1].max, group.indices[1].distinct) == (3, 7, 3)


def test_names_without_numbers_and_small_families_are_left_out():
    places = [
        named(place_id="a", name="idle"),
        named(place_id="b", name="x_1"),
        named(place_id="c", name="x_2"),
    ]
    structure = structure_of(places=places)
    assert name_groups(structure=structure, min_count=3) == ()
    assert [g.pattern for g in name_groups(structure=structure, min_count=2)] == ["x_{}"]


def test_unnamed_nodes_are_grouped_by_id():
    places = [Place(id="p1"), Place(id="p2"), Place(id="p3")]
    groups = name_groups(structure=structure_of(places=places), min_count=2)
    assert groups[0].pattern == "p{}"
    assert groups[0].example.name is None


def test_size_categories():
    assert size_category(structure=structure_of(places=[Place(id="p")])) == "small"
    big = structure_of(places=[Place(id=f"p{i}") for i in range(101)])
    assert size_category(structure=big) == "medium"


def test_neighbourhood_with_centers_beyond_the_cap_is_cut():
    structure = structure_of(
        places=[Place(id="a"), Place(id="b")], transitions=[Transition(id="t")]
    )
    result = neighbourhood(structure=structure, centers=("a", "b", "t"), depth=1, max_elements=2)
    assert result.cut is True
    assert len(result.elements) == 2


def test_neighbourhood_stops_when_nothing_is_left():
    structure = structure_of(
        places=[Place(id="a")],
        transitions=[Transition(id="t")],
        arcs=[Arc(id="x", source="a", target="t")],
    )
    result = neighbourhood(structure=structure, centers=("a",), depth=5, max_elements=10)
    assert [e.distance for e in result.elements] == [0, 1]
    assert result.cut is False


def test_the_marked_filter_needs_a_pt_net(store):
    from app.domain.canonical import net_id_of
    from app.domain.nets import summarize_document

    document = NetDocument(
        source_id="c",
        type_uri="http://www.pnml.org/version-2009/grammar/symmetricnet",
        places=(Place(id="p"),),
        transitions=(Transition(id="t"),),
    )
    net_id = net_id_of(document=document)
    store.save_net(summary=summarize_document(document=document, net_id=net_id), document=document)
    inspection = InspectionService(nets=store)
    with pytest.raises(InvalidRequestError):
        inspection.places(net_id=net_id, name=None, marked=True, page=PageRequest())
    with pytest.raises(InvalidRequestError):
        inspection.marking(net_id=net_id, page=PageRequest())
    assert inspection.overview(net_id=net_id).has_weighted_arcs is None
    with pytest.raises(NotFoundError):
        inspection.arcs(net_id=net_id, source="zzz", target=None, page=PageRequest())


def test_a_large_net_stays_within_the_size_budget(store):
    from app.domain.canonical import net_id_of
    from app.domain.nets import summarize_document

    count = 100_000
    document = NetDocument(
        source_id="big",
        type_uri=PTNET_TYPE_URI,
        places=tuple(named(place_id=f"p{i}", name=f"fork_{i}") for i in range(count)),
        transitions=(Transition(id="t"),),
    )
    net_id = net_id_of(document=document)
    store.save_net(summary=summarize_document(document=document, net_id=net_id), document=document)
    inspection = InspectionService(nets=store)

    started = time.perf_counter()
    groups = inspection.name_groups(net_id=net_id, min_count=2, page=PageRequest())
    first_page = inspection.places(net_id=net_id, name=None, marked=None, page=PageRequest())
    elapsed = time.perf_counter() - started

    assert len(groups.items) == 1
    assert groups.items[0].count == count
    assert len(groups.model_dump_json()) < 1_000  # a hundred thousand places, one short family
    assert len(first_page.model_dump_json()) < 20_000
    assert first_page.page.total == count
    assert elapsed < 60
