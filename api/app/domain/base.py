"""The base class of every domain model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base class of all models: immutable, so that no function can change its inputs."""

    model_config = ConfigDict(frozen=True)
