import inspect

import pytest
from pydantic import BaseModel, ValidationError

from app.domain import base, contract, models, net_document, net_validation
from app.domain.models import CheckRequest, DomainModel, Limits

ALL_MODELS = [
    cls
    for module in (base, models, contract, net_document, net_validation)
    for _, cls in inspect.getmembers(module, inspect.isclass)
    if issubclass(cls, BaseModel) and cls.__module__ == module.__name__
]


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda cls: cls.__name__)
def test_every_domain_model_is_immutable(model):
    """Architecture rule: data never changes after creation, so no function can mutate it."""
    assert model.model_config.get("frozen") is True


def test_there_are_models_to_check():
    assert DomainModel in ALL_MODELS
    assert len(ALL_MODELS) > 5


def test_a_frozen_model_rejects_assignment():
    with pytest.raises(ValidationError):
        Limits().timeout_s = 1  # type: ignore[misc]


def test_a_check_needs_at_least_one_formula():
    with pytest.raises(ValidationError):
        CheckRequest(formulas=())


def test_limits_are_bounded():
    with pytest.raises(ValidationError):
        Limits(timeout_s=0)
    with pytest.raises(ValidationError):
        Limits(memory_mb=1)
