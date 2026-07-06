"""Built-in processing steps — pure ``list[dict] -> list[dict]`` transforms.

Each step registers via ``@register_step`` and is constructed from its
``StepSpec.options``. No step reads the clock, the network, or disk.
"""

from __future__ import annotations

import re
import statistics
from typing import Callable

from datavibes.context import RunContext
from datavibes.errors import ConfigError, SchemaValidationError
from datavibes.interfaces import ProcessingStep
from datavibes.processing import functions
from datavibes.registry import register_step

_EXPR_PATTERN = re.compile(r"^\s*(\w+)\s*\((.*)\)\s*$")

DERIVE_FUNCTIONS: dict[str, Callable] = {
    "yoy": functions.yoy,
    "pct_change": functions.pct_change,
    "rolling_avg": functions.rolling_avg,
    "anomaly": functions.anomaly,
    "rolling_corr": functions.rolling_corr,
    # S07 primitive library
    "ratio": functions.ratio,
    "share": functions.share,
    "penetration": functions.penetration,
    "cagr": functions.cagr,
    "corr": functions.corr,
    "minmax_normalize": functions.minmax_normalize,
    "volatility": functions.volatility,
}


@register_step("normalize")
class NormalizeStep(ProcessingStep):
    """Coerce present schema columns to their dtypes; drop unknown columns."""

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        schema = ctx.config.schema
        column_names = schema.column_names()
        result: list[dict] = []
        for row in rows:
            normalized: dict = {}
            for name in column_names:
                if name in row:
                    normalized[name] = schema.field_for(name).coerce(row[name])
            result.append(normalized)
        return result


@register_step("dedupe")
class DedupeStep(ProcessingStep):
    """Remove duplicate rows by ``keys``, keeping the first or last occurrence."""

    def __init__(self, keys: list[str] | None = None, keep: str = "first"):
        if not keys:
            raise ConfigError("dedupe requires 'keys'")
        if keep not in ("first", "last"):
            raise ConfigError("dedupe 'keep' must be 'first' or 'last'")
        self.keys = keys
        self.keep = keep

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        chosen: dict[tuple, dict] = {}
        for row in rows:
            key = tuple(row.get(name) for name in self.keys)
            if self.keep == "first" and key in chosen:
                continue
            chosen[key] = row
        return list(chosen.values())


@register_step("derive")
class DeriveStep(ProcessingStep):
    """Add a computed column from a named pure helper over the row series.

    With ``by`` the helper is applied **within each group** (preserving row
    order) so windowed/growth/correlation helpers respect entity boundaries —
    e.g. a 5-year CAGR per country never spans two countries.
    """

    def __init__(self, column: str, expr: str, by: list[str] | None = None):
        if not column:
            raise ConfigError("derive requires a 'column'")
        if not expr:
            raise ConfigError("derive requires an 'expr'")
        self.column = column
        self.by = by or []
        self.func_name, self.positional, self.keywords = _parse_expr(expr)

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        helper = DERIVE_FUNCTIONS.get(self.func_name)
        if helper is None:
            raise ConfigError(
                f"derive: unknown helper '{self.func_name}' "
                f"(known: {', '.join(sorted(DERIVE_FUNCTIONS))})"
            )
        result = [dict(row) for row in rows]
        for indices in self._groups(rows):
            series_list = [
                [rows[i].get(column_name) for i in indices]
                for column_name in self.positional
            ]
            values = helper(*series_list, **self.keywords)
            for position, value in zip(indices, values):
                result[position][self.column] = value
        return result

    def _groups(self, rows: list[dict]) -> list[list[int]]:
        if not self.by:
            return [list(range(len(rows)))]
        order: list[tuple] = []
        buckets: dict[tuple, list[int]] = {}
        for index, row in enumerate(rows):
            key = tuple(row.get(name) for name in self.by)
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(index)
        return [buckets[key] for key in order]


@register_step("aggregate")
class AggregateStep(ProcessingStep):
    """Group by ``by`` and reduce ``metrics`` → one row per group."""

    _REDUCERS: dict[str, Callable[[list[float]], float]] = {
        "mean": lambda values: statistics.fmean(values),
        "median": lambda values: statistics.median(values),
        "min": min,
        "max": max,
        "sum": sum,
        "count": len,
    }

    def __init__(self, by: list[str] | None = None, metrics: dict | None = None):
        if not by:
            raise ConfigError("aggregate requires 'by'")
        if not metrics:
            raise ConfigError("aggregate requires 'metrics'")
        unknown = set(metrics.values()) - set(self._REDUCERS)
        if unknown:
            raise ConfigError(
                f"aggregate: unknown reducer(s) {', '.join(sorted(unknown))}"
            )
        self.by = by
        self.metrics = metrics

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        groups: dict[tuple, list[dict]] = {}
        for row in rows:
            key = tuple(row.get(name) for name in self.by)
            groups.setdefault(key, []).append(row)

        result: list[dict] = []
        for key in sorted(groups, key=_sort_key):
            group_rows = groups[key]
            aggregated = dict(zip(self.by, key))
            for column, reducer_name in self.metrics.items():
                reducer = self._REDUCERS[reducer_name]
                if reducer_name == "count":
                    aggregated[column] = reducer(group_rows)
                    continue
                numbers = [
                    float(item[column])
                    for item in group_rows
                    if item.get(column) is not None
                ]
                if numbers:
                    aggregated[column] = reducer(numbers)
                else:
                    # sum of nothing is 0; other reducers are undefined → None.
                    aggregated[column] = 0.0 if reducer_name == "sum" else None
            result.append(aggregated)
        return result


@register_step("sort")
class SortStep(ProcessingStep):
    """Stable-sort rows by ``by`` columns (nulls last) for deterministic output.

    Needed before windowed derives (``cagr``/``rolling_*``/``volatility``) so a
    per-entity series is time-ordered, and for byte-stable snapshots.
    """

    def __init__(self, by: list[str] | None = None):
        if not by:
            raise ConfigError("sort requires 'by'")
        self.by = by

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        return sorted(
            rows, key=lambda row: _sort_key(tuple(row.get(name) for name in self.by))
        )


@register_step("join")
class JoinStep(ProcessingStep):
    """Coalesce rows that share the ``on`` keys into one row per key.

    Sources land as separate rows carrying different columns for the same
    entity (e.g. World Bank indicator A and indicator B, both keyed by
    ``iso3``/``year``). ``join`` merges them: one output row per key with every
    non-null column unioned. Output is sorted by key for byte-stable snapshots.
    Later non-null values win on conflict.
    """

    def __init__(self, on: list[str] | None = None, how: str = "outer"):
        if not on:
            raise ConfigError("join requires 'on'")
        if how != "outer":
            raise ConfigError("join only supports how='outer'")
        self.on = on
        self.how = how

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        columns: list[str] = []
        for row in rows:
            for column in row:
                if column not in columns:
                    columns.append(column)
        merged: dict[tuple, dict] = {}
        for row in rows:
            key = tuple(row.get(name) for name in self.on)
            target = merged.setdefault(key, {column: None for column in columns})
            for name in self.on:
                target[name] = row.get(name)
            for column, value in row.items():
                if value is not None:
                    target[column] = value
        return [merged[key] for key in sorted(merged, key=_sort_key)]


@register_step("score")
class ScoreStep(ProcessingStep):
    """Weighted composite index from ``weights`` columns into ``column``.

    Each input column is min-max normalized across all rows (so mixed units
    combine), multiplied by its weight, summed, and scaled. Weights of absent
    (null) components are dropped and the remainder re-normalized, so a row with
    partial inputs still scores; a row with no inputs scores ``None``.
    """

    def __init__(
        self,
        column: str,
        weights: dict | None = None,
        scale: float = 1.0,
    ):
        if not column:
            raise ConfigError("score requires a 'column'")
        if not weights:
            raise ConfigError("score requires 'weights'")
        self.column = column
        self.weights = {name: float(weight) for name, weight in weights.items()}
        self.scale = float(scale)

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        normalized = {
            name: functions.minmax_normalize([row.get(name) for row in rows])
            for name in self.weights
        }
        result = [dict(row) for row in rows]
        for index, row in enumerate(result):
            weighted_sum = 0.0
            weight_total = 0.0
            for name, weight in self.weights.items():
                component = normalized[name][index]
                if component is None:
                    continue
                weighted_sum += weight * component
                weight_total += weight
            row[self.column] = (
                None if weight_total == 0 else self.scale * weighted_sum / weight_total
            )
        return result


@register_step("validate")
class ValidateStep(ProcessingStep):
    """Assert the rows conform to the schema; raise loudly if not."""

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        try:
            ctx.config.schema.validate(rows)
        except SchemaValidationError:
            raise
        return rows


def _sort_key(key: tuple) -> tuple:
    return tuple((value is None, str(value)) for value in key)


def _parse_expr(expr: str) -> tuple[str, list[str], dict]:
    match = _EXPR_PATTERN.match(expr)
    if not match:
        raise ConfigError(f"derive: cannot parse expr '{expr}'")
    func_name = match.group(1)
    positional: list[str] = []
    keywords: dict = {}
    for argument in _split_args(match.group(2)):
        if "=" in argument:
            name, raw_value = argument.split("=", 1)
            keywords[name.strip()] = _parse_literal(raw_value.strip())
        else:
            positional.append(argument.strip())
    return func_name, positional, keywords


def _split_args(arguments: str) -> list[str]:
    return [part.strip() for part in arguments.split(",") if part.strip()]


def _parse_literal(text: str):
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            continue
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text
