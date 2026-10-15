import pytest

from app.domain.contract import Marking, MarkingEntry, PageRequest
from app.domain.errors import InvalidRequestError
from app.domain.formula_text import parse_expression
from app.domain.net_document import PTNET_TYPE_URI, Arc, NetDocument, Place, Transition
from app.domain.net_structure import build_structure
from app.domain.replay import ReplayRequest, holds, replay
from tests.support import MUTEX_DOCUMENT

STRUCTURE = build_structure(document=MUTEX_DOCUMENT, net_id="n")


def run(*steps, **kwargs):
    return replay(structure=STRUCTURE, request=ReplayRequest(steps=steps, **kwargs))


def tokens_of(marking):
    return {e.place.id: e.tokens for e in marking.entries}


def test_a_valid_trace_reaches_the_expected_marking():
    result = run("enter1", "leave1")
    assert result.valid is True
    assert result.replayed == 2
    assert tokens_of(result.final_marking) == {"idle1": 1, "lock": 1}
    assert result.failure is None


def test_the_successive_markings_are_returned():
    result = run("enter1")
    assert len(result.markings) == 2
    assert tokens_of(result.markings[0]) == {"idle1": 1, "lock": 1}
    assert tokens_of(result.markings[1]) == {"crit1": 1}
    assert result.markings_total == 2


def test_a_firing_that_is_not_enabled_stops_the_replay_and_says_what_is_missing():
    result = run("enter1", "enter1")
    assert result.valid is False
    assert result.replayed == 1
    assert result.failure.step == 1
    assert result.failure.transition.id == "enter1"
    assert {(m.place.id, m.needed, m.available) for m in result.failure.missing} == {
        ("idle1", 1, 0),
        ("lock", 1, 0),
    }
    assert tokens_of(result.final_marking) == {"crit1": 1}


def test_the_empty_trace_is_valid_and_stays_at_the_initial_marking():
    result = run()
    assert result.valid
    assert tokens_of(result.final_marking) == {"idle1": 1, "lock": 1}


def test_a_start_marking_can_be_given():
    start = Marking(entries=(MarkingEntry(place={"id": "crit1", "kind": "place"}, tokens=1),))
    result = run("leave1", initial_marking=start)
    assert result.valid
    assert tokens_of(result.final_marking) == {"idle1": 1, "lock": 1}


def test_markings_are_paginated_without_losing_the_total():
    steps = ("enter1", "leave1") * 5
    first = run(*steps, page=PageRequest(limit=4))
    assert len(first.markings) == 4
    assert first.markings_total == 11
    later = run(*steps, page=PageRequest(limit=4, cursor=_cursor(4)))
    assert later.markings_from == 4
    assert tokens_of(later.markings[0]) == tokens_of(first.markings[0])  # 4 is a multiple of 2


def _cursor(offset):
    from app.domain.pagination import encode_cursor

    return encode_cursor(offset=offset)


def test_weights_are_honoured():
    document = NetDocument(
        source_id="w",
        type_uri=PTNET_TYPE_URI,
        places=(
            Place(id="p", initial_marking={"text": "3"}),
            Place(id="q"),
        ),
        transitions=(Transition(id="t"),),
        arcs=(
            Arc(id="a", source="p", target="t", inscription={"text": "2"}),
            Arc(id="b", source="t", target="q", inscription={"text": "5"}),
        ),
    )
    structure = build_structure(document=document, net_id="w")
    one = replay(structure=structure, request=ReplayRequest(steps=("t",)))
    assert tokens_of(one.final_marking) == {"p": 1, "q": 5}
    two = replay(structure=structure, request=ReplayRequest(steps=("t", "t")))
    assert two.valid is False
    assert two.failure.missing[0].needed == 2


@pytest.mark.parametrize("steps", [("nope",), ("crit1",)])
def test_ids_that_are_not_transitions_are_refused(steps):
    with pytest.raises(InvalidRequestError):
        run(*steps)


def test_an_unknown_place_in_the_start_marking_is_refused():
    start = Marking(entries=(MarkingEntry(place={"id": "zzz", "kind": "place"}, tokens=1),))
    with pytest.raises(InvalidRequestError):
        run(initial_marking=start)


def test_only_pt_nets_are_replayed():
    document = NetDocument(
        source_id="c",
        type_uri="http://www.pnml.org/version-2009/grammar/symmetricnet",
        places=(Place(id="p"),),
        transitions=(Transition(id="t"),),
    )
    with pytest.raises(InvalidRequestError, match="P/T"):
        replay(
            structure=build_structure(document=document, net_id="c"),
            request=ReplayRequest(steps=()),
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("crit1 >= 1", True),
        ("idle1 >= 1 && lock >= 1", False),
        ("idle1 + lock + crit1 = 1", True),
        ("fireable(leave1)", True),
        ("fireable(enter1)", False),
        ("deadlock", False),
        ("!(crit1 >= 1) -> true", True),
        ("crit1 >= 2 || false", False),
    ],
)
def test_state_conditions_on_the_marking_after_enter1(text, expected):
    result = run("enter1", state_formula=parse_expression(text=text))
    assert result.state_formula_holds is expected


def test_deadlock_holds_when_nothing_can_fire():
    document = NetDocument(
        source_id="d",
        type_uri=PTNET_TYPE_URI,
        places=(Place(id="p"),),
        transitions=(Transition(id="t"),),
        arcs=(Arc(id="a", source="p", target="t"),),
    )
    structure = build_structure(document=document, net_id="d")
    assert holds(expression=parse_expression(text="deadlock"), tokens={"p": 0}, structure=structure)


def test_a_temporal_formula_is_not_a_state_condition():
    with pytest.raises(InvalidRequestError, match="temporal"):
        run(state_formula=parse_expression(text="G crit1 >= 1"))


def test_the_state_formula_is_not_evaluated_when_the_replay_failed():
    result = run("leave1", state_formula=parse_expression(text="true"))
    assert result.valid is False
    assert result.state_formula_holds is None
