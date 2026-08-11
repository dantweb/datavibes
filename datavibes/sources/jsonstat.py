"""``jsonstat`` source — decode a JSON-stat 2.0 cube into tidy rows.

Eurostat and Japan's e-Stat publish every table as a *dense cube*: an ``id`` list
naming the dimensions, a ``size`` list giving each dimension's length, and a
``value`` map keyed by the flattened row-major offset. This adapter reverses the
flattening — offset → one category code per dimension — and emits one row per
present value.

``dimensions`` maps a JSON-stat dimension id to the output column that should
carry its **code** (``geo`` → ``geo_code``); a dimension left out is dropped,
which is how a config discards the singleton ``freq``/``unit`` axes it already
pinned server-side. ``label_columns`` additionally emits the human label
(``geo`` → ``country``) so a snapshot reads without a code book.
"""

from __future__ import annotations

from typing import Iterable

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry


@register_source("jsonstat")
class JsonStatSource(Source):
    """Fetch a JSON-stat 2.0 document and yield one row per present value."""

    def __init__(
        self,
        url: str,
        value_column: str,
        dimensions: dict | None = None,
        label_columns: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
    ):
        if not url:
            raise ConfigError("jsonstat source requires a 'url'")
        if not value_column:
            raise ConfigError("jsonstat source requires a 'value_column'")
        if not dimensions:
            raise ConfigError("jsonstat source requires a 'dimensions' mapping")
        self.url = url
        self.value_column = value_column
        self.dimensions = dict(dimensions)
        self.label_columns = dict(label_columns or {})
        self.params = dict(params or {})
        self.headers = dict(headers or {})

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        response = request_with_retry(
            ctx.http,
            self.url,
            params=self.params,
            headers=self.headers,
            settings=ctx.http_settings,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise SourceFetchError(f"GET {self.url} did not return JSON-stat") from exc
        return _decode(body, self.value_column, self.dimensions, self.label_columns)


def _decode(
    body: dict, value_column: str, dimensions: dict, label_columns: dict
) -> list[dict]:
    """Expand the dense cube in ``body`` into tidy rows (pure, testable)."""
    dimension_ids = body.get("id") or []
    sizes = body.get("size") or []
    if not dimension_ids or len(dimension_ids) != len(sizes):
        return []
    codes = [_codes_of(body, name) for name in dimension_ids]
    labels = [_labels_of(body, name) for name in dimension_ids]

    rows: list[dict] = []
    for offset, value in _values_of(body):
        if value is None:
            continue
        positions = _positions(offset, sizes)
        if positions is None:
            continue
        row: dict = {}
        for axis, name in enumerate(dimension_ids):
            column = dimensions.get(name)
            label_column = label_columns.get(name)
            if column is None and label_column is None:
                continue
            index = positions[axis]
            if index >= len(codes[axis]):
                continue
            code = codes[axis][index]
            if column is not None:
                row[column] = code
            if label_column is not None:
                row[label_column] = labels[axis].get(code, code)
        row[value_column] = value
        rows.append(row)
    return rows


def _values_of(body: dict) -> list[tuple[int, object]]:
    """The cube's values as ``(offset, value)`` — both encodings are legal."""
    values = body.get("value")
    if isinstance(values, dict):
        return sorted(
            ((int(key), value) for key, value in values.items()), key=lambda pair: pair[0]
        )
    if isinstance(values, list):
        return list(enumerate(values))
    return []


def _positions(offset: int, sizes: list[int]) -> list[int] | None:
    """Reverse the row-major flattening: offset → one index per dimension."""
    positions = [0] * len(sizes)
    remainder = offset
    for axis in range(len(sizes) - 1, -1, -1):
        size = sizes[axis]
        if size <= 0:
            return None
        positions[axis] = remainder % size
        remainder //= size
    return positions if remainder == 0 else None


def _codes_of(body: dict, name: str) -> list[str]:
    """Category codes of one dimension, ordered by their declared index."""
    index = _category(body, name).get("index") or {}
    if isinstance(index, dict):
        return [code for code, _ in sorted(index.items(), key=lambda pair: pair[1])]
    if isinstance(index, list):
        return list(index)
    return []


def _labels_of(body: dict, name: str) -> dict:
    label = _category(body, name).get("label") or {}
    return label if isinstance(label, dict) else {}


def _category(body: dict, name: str) -> dict:
    dimension = (body.get("dimension") or {}).get(name) or {}
    category = dimension.get("category") or {}
    return category if isinstance(category, dict) else {}
