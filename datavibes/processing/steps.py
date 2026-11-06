"""Built-in processing steps — pure ``list[dict] -> list[dict]`` transforms.

Each step registers via ``@register_step`` and is constructed from its
``StepSpec.options``. No step reads the clock, the network, or disk.
"""

from __future__ import annotations

import re
import statistics
from datetime import datetime, timezone
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
    # S12 primitive library
    "add": functions.add,
    "subtract": functions.subtract,
    "share_of_total": functions.share_of_total,
    "gini": functions.gini,
    "hhi": functions.hhi,
    "zscore": functions.zscore,
    "seasonal_index": functions.seasonal_index,
    "linear_forecast": functions.linear_forecast,
    "scale_to_range": functions.scale_to_range,
    "complement": functions.complement,
    "sex_majority": functions.sex_majority,
    "round_to": functions.round_to,
    "at_least": functions.at_least,
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

    def __init__(
        self,
        column: str,
        expr: str,
        by: list[str] | None = None,
        params: dict | None = None,
    ):
        if not column:
            raise ConfigError("derive requires a 'column'")
        if not expr:
            raise ConfigError("derive requires an 'expr'")
        self.column = column
        self.by = by or []
        self.func_name, self.positional, self.keywords = _parse_expr(expr)
        # ``params`` carry keyword values that can't live inside the expr string,
        # e.g. a YAML-anchored dataset parameter shared with a map colour scale.
        self.keywords.update(params or {})

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
        return _group_indices(rows, self.by)


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


@register_step("rename")
class RenameStep(ProcessingStep):
    """Rename source keys to schema column names before ``normalize`` drops them.

    Bulk CSV/JSON publishers name their columns for humans (``Annual CO₂
    emissions``, ``Entity``), never for a schema. Renaming here keeps the mapping
    declarative instead of pushing a bespoke adapter into every dataset that
    consumes a public CSV.
    """

    def __init__(self, columns: dict | None = None):
        if not columns:
            raise ConfigError("rename requires a 'columns' mapping")
        self.columns = dict(columns)

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        result: list[dict] = []
        for row in rows:
            renamed = {}
            for key, value in row.items():
                renamed[self.columns.get(key, key)] = value
            result.append(renamed)
        return result


@register_step("age_days")
class AgeDaysStep(ProcessingStep):
    """Whole days between an ISO-8601 timestamp column and the run instant.

    Staleness is the core risk signal of an OSS/model health dataset, and it is
    the one derivation that genuinely needs the run's timestamp. It reads that
    timestamp off the **injected** clock on the context — the same clock that
    stamps the snapshot filename — so a run remains reproducible: same config +
    same timestamp → same bytes. An unparseable or missing value yields ``None``.
    """

    def __init__(self, column: str, value: str):
        if not column:
            raise ConfigError("age_days requires a 'column'")
        if not value:
            raise ConfigError("age_days requires a 'value' column")
        self.column = column
        self.value = value

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        now = ctx.clock.now() if ctx.clock is not None else None
        result = [dict(row) for row in rows]
        for row in result:
            row[self.column] = _days_between(now, row.get(self.value))
        return result


def _days_between(now, value) -> int | None:
    if now is None or value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        try:
            moment = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    reference = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return (reference - moment).days


@register_step("flag")
class FlagStep(ProcessingStep):
    """Set a boolean ``column`` from one or more threshold/membership conditions.

    One condition goes in ``when``; several combine under ``all`` (logical AND)
    or ``any`` (logical OR). A condition names a ``column`` plus exactly the
    operators it needs — ``gt``/``gte``/``lt``/``lte``/``eq``/``ne``/``in``/
    ``not_in``/``is_null``/``not_null`` — and every operator listed must hold.
    A row whose value is missing simply fails an ordering test rather than
    raising, so a partially-populated dataset still flags.
    """

    def __init__(
        self,
        column: str,
        when: dict | None = None,
        all: list | None = None,  # noqa: A002 - the config keyword is 'all'
        any: list | None = None,  # noqa: A002 - the config keyword is 'any'
    ):
        if not column:
            raise ConfigError("flag requires a 'column'")
        provided = [block for block in (when, all, any) if block]
        if len(provided) != 1:
            raise ConfigError("flag requires exactly one of 'when', 'all', 'any'")
        self.column = column
        self.conditions = [when] if when else list(all or any or [])
        self.mode = "all" if (when or all) else "any"
        for condition in self.conditions:
            if not isinstance(condition, dict) or not condition.get("column"):
                raise ConfigError("flag condition requires a 'column'")

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        result = [dict(row) for row in rows]
        for row in result:
            outcomes = [_matches(row, condition) for condition in self.conditions]
            row[self.column] = all(outcomes) if self.mode == "all" else any(outcomes)
        return result


@register_step("filter")
class FilterStep(ProcessingStep):
    """Keep only the rows matching the condition(s) — same predicates as ``flag``.

    An outer ``join`` across sources of differing coverage legitimately produces
    rows where the headline measure never arrived (a geography present in one
    table and absent from another). Those rows are noise in a product a customer
    pays for, so a dataset drops them declaratively here rather than shipping
    columns of blanks.
    """

    def __init__(
        self,
        when: dict | None = None,
        all: list | None = None,  # noqa: A002 - the config keyword is 'all'
        any: list | None = None,  # noqa: A002 - the config keyword is 'any'
    ):
        provided = [block for block in (when, all, any) if block]
        if len(provided) != 1:
            raise ConfigError("filter requires exactly one of 'when', 'all', 'any'")
        self.conditions = [when] if when else list(all or any or [])
        self.mode = "all" if (when or all) else "any"
        for condition in self.conditions:
            if not isinstance(condition, dict) or not condition.get("column"):
                raise ConfigError("filter condition requires a 'column'")

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        kept: list[dict] = []
        for row in rows:
            outcomes = [_matches(row, condition) for condition in self.conditions]
            if all(outcomes) if self.mode == "all" else any(outcomes):
                kept.append(row)
        return kept


@register_step("classify")
class ClassifyStep(ProcessingStep):
    """Bucket a numeric ``value`` column into a labelled ``column``.

    ``bins`` are tried in order; the first whose ``min``/``max`` bounds contain
    the value wins (``min`` inclusive, ``max`` exclusive-of-the-next-bin i.e.
    ``value <= max``). A bin with neither bound is the catch-all. A missing or
    non-numeric value takes ``default``.
    """

    def __init__(
        self,
        column: str,
        value: str,
        bins: list | None = None,
        default: str | None = None,
    ):
        if not column:
            raise ConfigError("classify requires a 'column'")
        if not value:
            raise ConfigError("classify requires a 'value' column")
        if not bins:
            raise ConfigError("classify requires 'bins'")
        for entry in bins:
            if not isinstance(entry, dict) or not entry.get("label"):
                raise ConfigError("each classify bin requires a 'label'")
        self.column = column
        self.value = value
        self.bins = bins
        self.default = default

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        result = [dict(row) for row in rows]
        for row in result:
            row[self.column] = self._label_for(row.get(self.value))
        return result

    def _label_for(self, value: object) -> str | None:
        number = _as_number(value)
        if number is None:
            return self.default
        for entry in self.bins:
            low, high = entry.get("min"), entry.get("max")
            if low is not None and number < float(low):
                continue
            if high is not None and number > float(high):
                continue
            return entry["label"]
        return self.default


@register_step("forecast")
class ForecastStep(ProcessingStep):
    """Project ``value`` ``horizon`` periods ahead into ``column``.

    A trailing least-squares fit over the last ``window`` rows of each ``by``
    group is evaluated ``horizon`` positions past the current row — so an
    emissions series carries its own extrapolated trajectory alongside the
    observation. Rows before the window fills carry ``None``. Sort the rows by
    time first; the step trusts the row order it is given.
    """

    def __init__(
        self,
        column: str,
        value: str,
        by: list[str] | None = None,
        horizon: int = 1,
        window: int = 5,
        method: str = "linear",
    ):
        if not column:
            raise ConfigError("forecast requires a 'column'")
        if not value:
            raise ConfigError("forecast requires a 'value' column")
        if method != "linear":
            raise ConfigError("forecast only supports method='linear'")
        if horizon < 1:
            raise ConfigError("forecast 'horizon' must be >= 1")
        if window < 2:
            raise ConfigError("forecast 'window' must be >= 2")
        self.column = column
        self.value = value
        self.by = by or []
        self.horizon = horizon
        self.window = window

    def apply(self, rows: list[dict], ctx: RunContext) -> list[dict]:
        result = [dict(row) for row in rows]
        for indices in _group_indices(rows, self.by):
            series = [_as_number(rows[index].get(self.value)) for index in indices]
            projected = functions.linear_forecast(
                series, horizon=self.horizon, window=self.window
            )
            for position, value in zip(indices, projected):
                result[position][self.column] = value
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


def _group_indices(rows: list[dict], by: list[str]) -> list[list[int]]:
    """Row positions bucketed by the ``by`` columns, in first-seen order.

    Shared by every grouped step so a windowed computation never spans two
    entities (a 5-year CAGR, or a trend fit, stops at the country boundary).
    """
    if not by:
        return [list(range(len(rows)))]
    order: list[tuple] = []
    buckets: dict[tuple, list[int]] = {}
    for index, row in enumerate(rows):
        key = tuple(row.get(name) for name in by)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(index)
    return [buckets[key] for key in order]


def _as_number(value: object) -> float | None:
    """Best-effort numeric read — anything non-numeric reads as missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


_COMPARATORS: dict[str, Callable[[object, object], bool]] = {
    "gt": lambda left, right: left > right,
    "gte": lambda left, right: left >= right,
    "lt": lambda left, right: left < right,
    "lte": lambda left, right: left <= right,
}


def _matches(row: dict, condition: dict) -> bool:
    """Evaluate one ``flag`` condition against a row (every operator must hold)."""
    value = row.get(condition["column"])
    for operator, operand in condition.items():
        if operator == "column":
            continue
        if not _operator_holds(operator, value, operand):
            return False
    return True


def _operator_holds(operator: str, value: object, operand: object) -> bool:
    if operator == "is_null":
        return (value is None) is bool(operand)
    if operator == "not_null":
        return (value is not None) is bool(operand)
    if operator == "eq":
        return value == operand
    if operator == "ne":
        return value != operand
    if operator == "in":
        return value in (operand or [])
    if operator == "not_in":
        return value not in (operand or [])
    comparator = _COMPARATORS.get(operator)
    if comparator is None:
        raise ConfigError(
            f"flag: unknown operator '{operator}' "
            f"(known: {', '.join(sorted(_COMPARATORS))}, eq, ne, in, not_in, "
            f"is_null, not_null)"
        )
    number, threshold = _as_number(value), _as_number(operand)
    if number is None or threshold is None:
        return False
    return comparator(number, threshold)


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
