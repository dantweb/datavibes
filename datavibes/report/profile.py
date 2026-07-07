"""Deterministic dataset profiling — the factual grounding for the LLM.

The LLM never sees the raw dataset; it sees this compact, computed profile
(row count, per-column stats, distributions). Grounding the model in real
numbers keeps the generated analytics accurate rather than invented. Pure
functions only — no clock, network, or disk.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from datavibes.config.models import DatasetConfig

_NUMERIC_DTYPES = {"int", "float"}
_TOP_VALUES = 5


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    unit: str | None
    count: int
    non_null: int
    # Numeric columns:
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    # Categorical columns:
    distinct: int | None = None
    top_values: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class DatasetProfile:
    slug: str
    title: str
    category: str
    row_count: int
    columns: list[ColumnProfile]


def build_profile(config: DatasetConfig, rows: list[dict]) -> DatasetProfile:
    """Compute a factual profile of ``rows`` against the dataset schema."""
    columns = [
        _profile_column(field.name, field.dtype, field.unit, rows)
        for field in config.schema.fields
    ]
    return DatasetProfile(
        slug=config.slug,
        title=config.metadata.title,
        category=config.category,
        row_count=len(rows),
        columns=columns,
    )


def _profile_column(
    name: str, dtype: str, unit: str | None, rows: list[dict]
) -> ColumnProfile:
    values = [row.get(name) for row in rows]
    present = [value for value in values if value is not None and value != ""]
    profile = ColumnProfile(
        name=name,
        dtype=dtype,
        unit=unit,
        count=len(values),
        non_null=len(present),
    )
    if dtype in _NUMERIC_DTYPES:
        _fill_numeric(profile, present)
    else:
        _fill_categorical(profile, present)
    return profile


def _fill_numeric(profile: ColumnProfile, present: list) -> None:
    numbers = []
    for value in present:
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return
    profile.minimum = min(numbers)
    profile.maximum = max(numbers)
    profile.mean = statistics.fmean(numbers)
    profile.median = statistics.median(numbers)
    profile.stdev = statistics.stdev(numbers) if len(numbers) > 1 else 0.0


def _fill_categorical(profile: ColumnProfile, present: list) -> None:
    counts: dict[str, int] = {}
    for value in present:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    profile.distinct = len(counts)
    profile.top_values = sorted(
        counts.items(), key=lambda item: (-item[1], item[0])
    )[:_TOP_VALUES]
