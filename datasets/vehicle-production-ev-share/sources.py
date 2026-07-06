"""Bespoke ``iea-ev`` source for the Vehicle Production → EV Share dataset.

The IEA Global EV Data API (``api.iea.org/evs``, keyless) returns long-format
rows — one per ``parameter`` (``EV sales``, ``EV sales share``, ``EV charging
points``) per region-year — that must be pivoted to one wide row per country
before any statistics apply. This ~1-screen :class:`Source` filters to the
configured ``mode``/``category`` and sums each parameter into its schema column.
Regions are country names (the API carries no ISO3); grouping is by name.
"""

from __future__ import annotations

from typing import Iterable

from datavibes.context import FetchContext
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

IEA_EV_URL = "https://api.iea.org/evs"


@register_source("iea-ev")
class IeaEvSource(Source):
    """Fetch IEA EV records and pivot parameters → one wide row per country-year."""

    def __init__(
        self,
        parameters: dict[str, str] | None = None,
        mode: str = "Cars",
        category: str = "Historical",
    ):
        # ``parameters`` maps an IEA parameter name → the schema column it feeds.
        self.parameters = parameters or {}
        self.mode = mode
        self.category = category

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        params = {
            "parameters": ",".join(self.parameters),
            "category": self.category,
            "mode": self.mode,
            "csv": "false",
        }
        response = request_with_retry(
            ctx.http, IEA_EV_URL, params=params, headers={}, settings=ctx.http_settings
        )
        records = _as_list(response.json())

        pivoted: dict[tuple, dict] = {}
        for item in records:
            column = self.parameters.get(item.get("parameter"))
            if column is None:
                continue
            if item.get("mode") != self.mode or item.get("category") != self.category:
                continue
            region = item.get("region")
            year = item.get("year")
            value = item.get("value")
            if region is None or year is None or value is None:
                continue
            key = (region, year)
            row = pivoted.setdefault(key, {"country": region, "year": year})
            row[column] = row.get(column, 0.0) + float(value)
        return list(pivoted.values())


def _as_list(body: object) -> list[dict]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []
