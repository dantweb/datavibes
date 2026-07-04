"""``http_csv`` source — GET a CSV document, stream rows to dicts."""

from __future__ import annotations

import csv
import io
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry


@register_source("http_csv")
class HttpCsvSource(Source):
    """Fetch a CSV document and yield one dict per data row (header-driven)."""

    def __init__(
        self,
        url: str,
        delimiter: str = ",",
        encoding: str = "utf-8",
        headers: dict | None = None,
        params: dict | None = None,
    ):
        if not url:
            raise ValueError("http_csv source requires a 'url'")
        self.url = url
        self.delimiter = delimiter
        self.encoding = encoding
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
        text = self._body_text(response)
        reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
        return [dict(row) for row in reader]

    def _body_text(self, response: object) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            return content.decode(self.encoding)
        return str(getattr(response, "text", ""))
