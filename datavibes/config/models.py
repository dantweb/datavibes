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


CHART_TYPES = ("bar", "line", "scatter", "area")


@dataclass
class ChartSpec:
    """A declared chart for the dataset report (rendered to a PNG + embedded in the PDF).

    See ``docs/charts.md`` for the full field reference. ``x``/``y`` are column
    names; ``series`` splits ``y`` into one line/bar-group per distinct value;
    ``agg`` reduces multiple rows sharing an ``x`` (mean/sum/median/min/max);
    ``filter`` subsets rows by exact column values; ``sort``/``limit`` pick and
    order the points shown.
    """

    type: str
    title: str
    x: str
    y: str
    series: str | None = None
    agg: str | None = None
    filter: dict = field(default_factory=dict)
    sort: dict = field(default_factory=dict)
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.type not in CHART_TYPES:
            raise ConfigError(
                f"chart type '{self.type}' unsupported "
                f"(expected one of {', '.join(CHART_TYPES)})"
            )
        if not self.title:
            raise ConfigError("chart requires a 'title'")
        if not self.x or not self.y:
            raise ConfigError(f"chart '{self.title}' requires 'x' and 'y'")


@dataclass
class DatasetConfig:
    """The fully parsed ``dataset.yaml``."""

    metadata: DatasetMetadata
    schema: Schema
    sources: list[SourceSpec] = field(default_factory=list)
    processing: list[StepSpec] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)

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
