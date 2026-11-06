"""``sparql`` — any SPARQL 1.1 endpoint (Wikidata by default), keyless.

The query lives in ``dataset.yaml`` (``${VAR:-default}`` interpolation applies,
so thresholds can be tuned per run). Each result binding becomes one flat record
keyed by the query's variables; every ``head.vars`` column is present (``None``
when unbound) so ``validate`` sees a uniform shape. Numeric XSD literals are cast
to ``float``; URIs can be shortened to their last path segment (``Q64``).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# Wikidata allows a query up to 60 s server-side; the SDK-wide HTTP timeout (30 s)
# is tuned for plain REST calls and would abort a heavy-but-valid query.
DEFAULT_TIMEOUT_SECONDS = 90.0
_XSD = "http://www.w3.org/2001/XMLSchema#"
_NUMERIC_TYPES = {
    _XSD + name
    for name in ("integer", "decimal", "double", "float", "int", "long", "nonNegativeInteger")
}


@register_source("sparql")
class SparqlSource(Source):
    """Run one SELECT query and yield its bindings as flat records."""

    def __init__(
        self,
        query: str,
        endpoint: str = WIKIDATA_SPARQL,
        strip_uri_prefix: bool = False,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if not query or not str(query).strip():
            raise ConfigError("sparql requires a non-empty 'query'")
        self.query = str(query)
        self.endpoint = endpoint
        self.strip_uri_prefix = strip_uri_prefix
        self.timeout_seconds = float(timeout_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        response = request_with_retry(
            ctx.http,
            self.endpoint,
            params={"query": self.query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            settings=replace(ctx.http_settings, timeout_seconds=self.timeout_seconds),
        )
        body = response.json()
        try:
            variables = list(body["head"]["vars"])
            bindings = body["results"]["bindings"]
        except (KeyError, TypeError) as exc:
            raise SourceFetchError(f"SPARQL endpoint {self.endpoint} returned no results: {body!r:.300}") from exc
        return [
            {name: self._value(binding.get(name)) for name in variables}
            for binding in bindings
        ]

    def _value(self, cell: dict | None) -> object:
        if cell is None:
            return None
        value = cell.get("value")
        if cell.get("type") == "uri" and self.strip_uri_prefix:
            return value.rstrip("/").rsplit("/", 1)[-1]
        if cell.get("datatype") in _NUMERIC_TYPES:
            return float(value)
        return value
