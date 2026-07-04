"""Built-in source adapters. Importing this package registers them all."""

from datavibes.sources.http_csv import HttpCsvSource
from datavibes.sources.http_json import HttpJsonSource
from datavibes.sources.static import StaticSource

__all__ = ["StaticSource", "HttpJsonSource", "HttpCsvSource"]
