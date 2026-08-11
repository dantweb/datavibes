"""``paged_http_json`` source — walk a paged JSON API into one flat record list.

Covers the three paging dialects the public catalogue sources actually use:

* ``page``   — a 1-based page number parameter (GitHub, Hugging Face, TED)
* ``offset`` — a row offset plus a limit (Comtrade, most SQL-backed portals)
* ``cursor`` — the response carries the *next* absolute URL (`select`-ed)

Paging stops at the first empty or short page, or at ``max_pages`` — whichever
comes first — so a cron can never walk an unbounded feed. An optional
``token_env`` names the environment variable holding a bearer token; the token
itself never appears in the config (secrets live in ``.env`` only).
"""

from __future__ import annotations

import os
import time
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.selector import select
from datavibes.sources.http_client import request_with_retry
from datavibes.sources.mapping import project, read_path

PAGING_MODES = ("page", "offset", "cursor")


@register_source("paged_http_json")
class PagedHttpJsonSource(Source):
    """Fetch every page of a JSON endpoint and yield the ``select``-ed records."""

    def __init__(
        self,
        url: str,
        select: str = "$[*]",
        paging: str = "page",
        fields: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        page_param: str = "page",
        page_size_param: str = "per_page",
        page_size: int = 100,
        start_page: int = 1,
        offset_param: str = "offset",
        cursor_select: str = "",
        max_pages: int = 10,
        token_env: str = "",
        auth_scheme: str = "Bearer",
        delay_seconds: float = 0.0,
    ):
        if not url:
            raise ConfigError("paged_http_json source requires a 'url'")
        if paging not in PAGING_MODES:
            raise ConfigError(
                f"paged_http_json 'paging' must be one of {', '.join(PAGING_MODES)}"
            )
        if paging == "cursor" and not cursor_select:
            raise ConfigError("paged_http_json cursor paging requires 'cursor_select'")
        self.url = url
        self.select_expression = select
        self.paging = paging
        self.fields = dict(fields or {})
        self.params = dict(params or {})
        self.headers = dict(headers or {})
        self.page_param = page_param
        self.page_size_param = page_size_param
        self.page_size = int(page_size)
        self.start_page = int(start_page)
        self.offset_param = offset_param
        self.cursor_select = cursor_select
        self.max_pages = max(1, int(max_pages))
        self.token_env = token_env
        self.auth_scheme = auth_scheme
        self.delay_seconds = float(delay_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        headers = _authorized(self.headers, self.token_env, self.auth_scheme)
        records: list[dict] = []
        url = self.url
        for page in range(self.max_pages):
            if page and self.delay_seconds:
                time.sleep(self.delay_seconds)
            params = self._params_for(page)
            response = request_with_retry(
                ctx.http, url, params=params, headers=headers, settings=ctx.http_settings
            )
            body = _json_of(response, url)
            batch = list(select(body, self.select_expression))
            records.extend(project(record, self.fields) for record in batch)
            if self.paging == "cursor":
                url = self._next_url(body)
                if not url:
                    break
                continue
            if len(batch) < self.page_size:
                break
        return records

    def _params_for(self, page_index: int) -> dict:
        params = dict(self.params)
        if self.paging == "page":
            params[self.page_param] = self.start_page + page_index
            params.setdefault(self.page_size_param, self.page_size)
        elif self.paging == "offset":
            params[self.offset_param] = page_index * self.page_size
            params.setdefault(self.page_size_param, self.page_size)
        return params

    def _next_url(self, body: object) -> str:
        candidate = read_path(body, self.cursor_select.lstrip("$."))
        return candidate if isinstance(candidate, str) else ""


def _authorized(headers: dict, token_env: str, scheme: str) -> dict:
    """Add an ``Authorization`` header when the named env var holds a token."""
    merged = dict(headers)
    token = os.environ.get(token_env, "").strip() if token_env else ""
    if token:
        merged["Authorization"] = f"{scheme} {token}".strip()
    return merged


def _json_of(response: object, url: str) -> object:
    try:
        return response.json()  # type: ignore[attr-defined]
    except ValueError as exc:
        raise SourceFetchError(f"GET {url} did not return valid JSON") from exc
