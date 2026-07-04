"""Config models — the whole per-dataset contract, validated on construction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from datavibes.errors import ConfigError
from datavibes.schema.field import Schema

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class DatasetMetadata:
    """Descriptive, non-executable facts about a dataset."""

    slug: str
    title: str
    category: str
    license: str = ""
    update_frequency: str = ""
    attribution: str = ""

    def __post_init__(self) -> None:
        if not _KEBAB_CASE.match(self.slug or ""):
            raise ConfigError(f"slug '{self.slug}' must be kebab-case")
        if not self.title:
            raise ConfigError("metadata.title must be non-empty")
        if not self.category:
            raise ConfigError("metadata.category must be non-empty")


@dataclass
class SourceSpec:
    """A declared source: its registry ``type`` + free-form ``options``."""

    type: str
    options: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.type:
            raise ConfigError("source.type must be non-empty")


@dataclass
class StepSpec:
    """A declared processing step: its registry ``name`` + ``options``."""

    name: str
    options: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("processing step name must be non-empty")


@dataclass
class DatasetConfig:
    """The fully parsed ``dataset.yaml``."""

    metadata: DatasetMetadata
    schema: Schema
    sources: list[SourceSpec] = field(default_factory=list)
    processing: list[StepSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.schema.fields:
            raise ConfigError("schema must declare at least one field")
        if not self.sources:
            raise ConfigError("at least one source is required")

    @property
    def slug(self) -> str:
        return self.metadata.slug

    @property
    def category(self) -> str:
        return self.metadata.category
