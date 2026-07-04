"""``http_json`` source — GET a JSON API, select the record array."""

from __future__ import annotations

from typing import Iterable

from datavibes.context import FetchContext
from datavibes.errors import SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.selector import select
from datavibes.sources.http_client import request_with_retry


@register_source("http_json")
class HttpJsonSource(Source):
    """Fetch a JSON document and yield the ``select``-ed records."""

    def __init__(
        self,
        url: str,
        select: str = "$",
        headers: dict | None = None,
        params: dict | None = None,
    ):
        if not url:
            raise ValueError("http_json source requires a 'url'")
        self.url = url
        self.select_expression = select
        self.headers = headers or {}
        self.params = params or {}

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
            raise SourceFetchError(
                f"GET {self.url} did not return valid JSON"
            ) from exc
        return list(select(body, self.select_expression))
