import json
from pathlib import Path

import pytest
from jsonschema import validate

from app.domain.schemas import EXPORTED_MODELS, render_schema

SCHEMAS = Path(__file__).resolve().parents[3] / "docs" / "schemas"


@pytest.mark.parametrize("model", EXPORTED_MODELS, ids=lambda model: model.__name__)
def test_committed_schema_is_current(model):
    """Fails when a model changed without running `make schemas`."""
    committed = (SCHEMAS / f"{model.__name__}.schema.json").read_text()
    assert committed == render_schema(model=model)


def test_no_orphan_schema_is_committed():
    committed = {path.name for path in SCHEMAS.glob("*.schema.json")}
    assert committed == {f"{model.__name__}.schema.json" for model in EXPORTED_MODELS}


def test_engines_response_validates_against_the_envelope_schema(client):
    schema = json.loads((SCHEMAS / "Envelope.schema.json").read_text())
    validate(instance=client.get("/v1/engines").json(), schema=schema)
