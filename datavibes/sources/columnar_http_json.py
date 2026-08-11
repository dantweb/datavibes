"""``columnar_http_json`` source — transpose parallel arrays into tidy rows.

Time-series APIs almost never return records. They return one index array plus
one array per measure, all the same length (Open-Meteo's ``hourly`` block,
energy-charts' ``unix_seconds`` + ``price``). This adapter zips them back into
one row per index position, fans out over ``items`` the same way
``multi_http_json`` does, and tolerates a value array that is shorter than the
index (a trailing gap becomes ``None`` rather than truncating the series).
"""

from __future__ import annotations

import time
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.errors import ConfigError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.selector import select
from datavibes.sources.http_client import request_with_retry
from datavibes.sources.mapping import carried, read_path, render_params, render_template
from datavibes.sources.paged_http_json import _authorized


@register_source("columnar_http_json")
class ColumnarHttpJsonSource(Source):
    """One request per item → one row per position of the index array."""

    def __init__(
        self,
        url: str,
        index: str,
        fields: dict | None = None,
        items: list | None = None,
        index_column: str = "",
        select: str = "$",
        carry: list[str] | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        token_env: str = "",
        auth_scheme: str = "Bearer",
        delay_seconds: float = 0.0,
        max_rows: int = 0,
    ):
        if not url:
            raise ConfigError("columnar_http_json source requires a 'url'")
        if not index:
            raise ConfigError("columnar_http_json source requires an 'index' array")
        if not fields:
            raise ConfigError("columnar_http_json source requires a 'fields' mapping")
        self.url = url
        self.index = index
        self.index_column = index_column or index
        self.fields = dict(fields)
        self.items = [dict(item) for item in (items or [{}])]
        self.select_expression = select
        self.carry = carry
        self.params = dict(params or {})
        self.headers = dict(headers or {})
        self.token_env = token_env
        self.auth_scheme = auth_scheme
        self.delay_seconds = float(delay_seconds)
        self.max_rows = max(0, int(max_rows))

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        headers = _authorized(self.headers, self.token_env, self.auth_scheme)
        rows: list[dict] = []
        for position, item in enumerate(self.items):
            if position and self.delay_seconds:
                time.sleep(self.delay_seconds)
            node = self._fetch_item(ctx, item, headers)
            if node is None:
                continue
            rows.extend(self._rows_for(item, node))
        return rows

    def _fetch_item(self, ctx: FetchContext, item: dict, headers: dict) -> dict | None:
        url = render_template(self.url, item)
        try:
            response = request_with_retry(
                ctx.http,
                url,
                params=render_params(self.params, item),
                headers=headers,
                settings=ctx.http_settings,
            )
            body = response.json()
        except Exception:  # one dead endpoint costs one item, never the snapshot
            return None
        selected = list(select(body, self.select_expression))
        return selected[0] if selected else None

    def _rows_for(self, item: dict, node: dict) -> list[dict]:
        index_values = read_path(node, self.index)
        if not isinstance(index_values, list):
            return []
        columns = {
            column: read_path(node, path) for column, path in self.fields.items()
        }
        length = len(index_values)
        if self.max_rows:
            length = min(length, self.max_rows)
        base = carried(item, self.carry)
        rows: list[dict] = []
        for position in range(length):
            row = dict(base)
            row[self.index_column] = index_values[position]
            for column, series in columns.items():
                row[column] = _at(series, position)
            rows.append(row)
        return rows


def _at(series: object, position: int):
    if isinstance(series, list):
        return series[position] if position < len(series) else None
    return series
