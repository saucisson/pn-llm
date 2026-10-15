"""Round trips on real contest data (tests/corpus/mcc, see its README)."""

from pathlib import Path

import pytest

from app.domain.canonical import behaviour_id_of, net_id_of
from app.domain.formula_text import parse_expression, render_text
from app.domain.mcc_properties import EXAMINATIONS, parse_property_set
from app.domain.net_validation import DocumentLimits, parse_document
from app.domain.pnml_export import render_pnml
from app.domain.pnml_import import import_pnml

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "mcc"
INSTANCES = sorted(path.name for path in CORPUS.iterdir() if path.is_dir())
LIMITS = DocumentLimits()


@pytest.mark.parametrize("instance", INSTANCES)
def test_pnml_is_a_fixed_point_and_json_gives_the_same_id(instance):
    original = import_pnml(payload=(CORPUS / instance / "model.pnml").read_bytes(), limits=LIMITS)
    exported = render_pnml(document=original)
    again = import_pnml(payload=exported, limits=LIMITS)
    assert net_id_of(document=again) == net_id_of(document=original)
    assert render_pnml(document=again) == exported
    as_json = parse_document(payload=original.model_dump_json().encode(), limits=LIMITS)
    assert net_id_of(document=as_json) == net_id_of(document=original)
    assert behaviour_id_of(document=as_json) == behaviour_id_of(document=original)


def test_the_corpus_has_both_kinds_of_nets():
    kinds = {
        instance: import_pnml(
            payload=(CORPUS / instance / "model.pnml").read_bytes(), limits=LIMITS
        ).type_uri
        for instance in INSTANCES
    }
    assert any(uri.endswith("symmetricnet") for uri in kinds.values())
    assert any(not uri.endswith("symmetricnet") for uri in kinds.values())


@pytest.mark.parametrize("instance", INSTANCES)
@pytest.mark.parametrize("examination", EXAMINATIONS)
def test_contest_formulas_survive_the_text_round_trip(instance, examination):
    parsed = parse_property_set(
        examination=examination, xml=(CORPUS / instance / f"{examination}.xml").read_bytes()
    )
    assert parsed.formulas or parsed.bounds
    for formula in parsed.formulas:
        assert parse_expression(text=render_text(expression=formula.ast)) == formula.ast
