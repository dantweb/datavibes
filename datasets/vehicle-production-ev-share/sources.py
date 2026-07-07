"""Bespoke ``iea-ev`` source for the Vehicle Production → EV Share dataset.

The IEA Global EV Data API (``api.iea.org/evs``, keyless) returns long-format
rows — one per ``(region, parameter, mode, powertrain, year)`` — and **requires**
a ``year`` (or ``region``) per request. A single year request returns every
parameter/mode for all regions, so the adapter loops the configured ``years``
and pivots to one wide row per ``(country, year)``.

Each configured metric pins the ``parameter`` **and its mode** (they differ:
sales live under ``Cars``, charging points under ``EVSE``) and, optionally, the
physical ``powertrains`` to sum — because summing across every powertrain or
mode would double-count. Regions are country/aggregate names (the API carries no
ISO3); grouping is by name. No secret is required.
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
    """Fetch IEA EV data per year and pivot metrics → one wide row per country-year."""

    def __init__(
        self,
        metrics: list[dict] | None = None,
        years: list[int] | None = None,
        category: str = "Historical",
    ):
        # Each metric: {parameter, column, mode, powertrains?}. ``powertrains``
        # (optional) restricts which rows are summed into the column.
        self.metrics = metrics or []
        self.years = years or []
        self.category = category

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        pivoted: dict[tuple, dict] = {}
        for year in self.years:
            for item in self._fetch_year(ctx, year):
                self._accumulate(pivoted, item)
        return list(pivoted.values())

    def _fetch_year(self, ctx: FetchContext, year: int) -> list[dict]:
        params = {"category": self.category, "year": year}
        response = request_with_retry(
            ctx.http, IEA_EV_URL, params=params, headers={}, settings=ctx.http_settings
        )
        body = response.json()
        return body if isinstance(body, list) else []

    def _accumulate(self, pivoted: dict[tuple, dict], item: dict) -> None:
        region = item.get("region")
        year = item.get("year")
        value = item.get("value")
        if region is None or year is None or value is None:
            return
        for metric in self.metrics:
            if not self._matches(item, metric):
                continue
            column = metric["column"]
            key = (region, year)
            row = pivoted.get(key)
            if row is None:
                # Seed every configured column to None so a (region, year) with
                # only some metrics (e.g. sales but no charging data) still yields
                # a complete, schema-valid row.
                row = {"country": region, "year": year}
                for other in self.metrics:
                    row[other["column"]] = None
                pivoted[key] = row
            row[column] = (row.get(column) or 0.0) + float(value)

    @staticmethod
    def _matches(item: dict, metric: dict) -> bool:
        if item.get("parameter") != metric.get("parameter"):
            return False
        if item.get("mode") != metric.get("mode"):
            return False
        powertrains = metric.get("powertrains")
        if powertrains and item.get("powertrain") not in powertrains:
            return False
        return True
