"""Built-in source adapters. Importing this package registers them all."""

from datavibes.sources.columnar_http_json import ColumnarHttpJsonSource
from datavibes.sources.http_csv import HttpCsvSource
from datavibes.sources.http_json import HttpJsonSource
from datavibes.sources.jsonstat import JsonStatSource
from datavibes.sources.multi_http_json import MultiHttpJsonSource
from datavibes.sources.paged_http_json import PagedHttpJsonSource
from datavibes.sources.static import StaticSource
from datavibes.sources.worldbank import WorldBankIndicatorSource
from datavibes.sources.sparql import SparqlSource
from datavibes.sources.worldbank_latest import WorldBankLatestSource

__all__ = [
    "StaticSource",
    "HttpJsonSource",
    "HttpCsvSource",
    "PagedHttpJsonSource",
    "MultiHttpJsonSource",
    "ColumnarHttpJsonSource",
    "JsonStatSource",
    "WorldBankIndicatorSource",
    "WorldBankLatestSource",
    "SparqlSource",
]
