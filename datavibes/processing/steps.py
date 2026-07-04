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
    """Add a computed column from a named pure helper over the row series."""

    def __init__(self, column: str, expr: str):
        if not column:
            raise ConfigError("derive requires a 'column'")
        if not expr:
            raise ConfigError("derive requires an 'expr'")
        self.column = column
        self.func_name, self.positional, self.keywords = _parse_expr(expr)

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        helper = DERIVE_FUNCTIONS.get(self.func_name)
        if helper is None:
            raise ConfigError(
                f"derive: unknown helper '{self.func_name}' "
                f"(known: {', '.join(sorted(DERIVE_FUNCTIONS))})"
            )
        series_list = [
            [row.get(column_name) for row in rows] for column_name in self.positional
        ]
        values = helper(*series_list, **self.keywords)
        result = [dict(row) for row in rows]
        for row, value in zip(result, values):
            row[self.column] = value
        return result


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
