import pytest

from app.domain import pnml
from app.domain.errors import PnmlError


def test_summarizes_counts_and_keeps_names(mutex_pnml):
    net = pnml.summarize(pnml=mutex_pnml)
    assert (net.places, net.transitions, net.arcs) == (3, 2, 6)
    assert net.place_names == ("idle1", "crit1", "lock")
    assert net.transition_names == ("enter1", "leave1")
    assert net.initial_tokens == 2


def test_net_id_is_a_stable_content_hash(mutex_pnml):
    first = pnml.summarize(pnml=mutex_pnml)
    assert first.net_id == pnml.summarize(pnml=mutex_pnml).net_id
    assert first.net_id != pnml.summarize(pnml=mutex_pnml + b"<!-- changed -->").net_id


def test_falls_back_to_the_id_when_an_element_has_no_name():
    net = pnml.summarize(pnml=b'<pnml><net><place id="p1"/><transition id="t1"/></net></pnml>')
    assert net.place_names == ("p1",)
    assert net.transition_names == ("t1",)


def test_non_numeric_initial_marking_counts_as_zero():
    xml = (
        b'<pnml><net><place id="p"><initialMarking><text>many</text></initialMarking></place>'
        b'<transition id="t"/></net></pnml>'
    )
    assert pnml.summarize(pnml=xml).initial_tokens == 0


def test_xml_namespaces_are_ignored():
    xml = (
        b'<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml"><net>'
        b'<place id="p"/><transition id="t"/></net></pnml>'
    )
    assert pnml.summarize(pnml=xml).places == 1


@pytest.mark.parametrize(
    "payload",
    [
        b"<not xml",
        b"<pnml><net><page/></net></pnml>",  # no place, no transition
        b'<pnml><net><place id="p"/></net></pnml>',  # no transition
    ],
)
def test_rejects_invalid_or_empty_nets(payload):
    with pytest.raises(PnmlError):
        pnml.summarize(pnml=payload)


def test_rejects_entity_expansion_payloads():
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        b'<pnml><net><place id="p">&b;</place><transition id="t"/></net></pnml>'
    )
    with pytest.raises(PnmlError):
        pnml.summarize(pnml=bomb)
