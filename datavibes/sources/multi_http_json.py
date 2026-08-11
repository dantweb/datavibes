"""``multi_http_json`` source — fan out over a declared item list, one row each.

The catalogue is full of "N entities, one endpoint each" sources: a GitHub repo
per OSS project, an npm/PyPI package per library, a search query per language.
This adapter renders ``{key}`` placeholders from each item into the URL and the
query params, maps the response through ``fields`` (dotted paths welcome), and
copies the item's own keys onto the row so the entity stays identified.

An item whose request fails is **skipped**, not fatal: a rate-limited or retired
endpoint costs one row, never the whole snapshot. ``delay_seconds`` paces the
loop for APIs that meter unauthenticated callers.
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
from datavibes.sources.mapping import carried, project, render_params, render_template
from datavibes.sources.paged_http_json import _authorized


@register_source("multi_http_json")
class MultiHttpJsonSource(Source):
    """One request per declared item → one flat record per successful item."""

    def __init__(
        self,
        url: str,
        items: list | None = None,
        fields: dict | None = None,
        select: str = "$",
        carry: list[str] | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        token_env: str = "",
        auth_scheme: str = "Bearer",
        delay_seconds: float = 0.0,
    ):
        if not url:
            raise ConfigError("multi_http_json source requires a 'url'")
        if not items:
            raise ConfigError("multi_http_json source requires a non-empty 'items'")
        if not fields:
            raise ConfigError("multi_http_json source requires a 'fields' mapping")
        self.url = url
        self.items = [dict(item) for item in items]
        self.fields = dict(fields)
        self.select_expression = select
        self.carry = carry
        self.params = dict(params or {})
        self.headers = dict(headers or {})
        self.token_env = token_env
        self.auth_scheme = auth_scheme
        self.delay_seconds = float(delay_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        headers = _authorized(self.headers, self.token_env, self.auth_scheme)
        rows: list[dict] = []
        for position, item in enumerate(self.items):
            if position and self.delay_seconds:
                time.sleep(self.delay_seconds)
            record = self._fetch_item(ctx, item, headers)
            if record is None:
                continue
            rows.append({**carried(item, self.carry), **project(record, self.fields)})
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
        except Exception:  # one dead endpoint costs one row, never the snapshot
            return None
        selected = list(select(body, self.select_expression))
        return selected[0] if selected else None
