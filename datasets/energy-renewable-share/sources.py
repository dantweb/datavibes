"""Bespoke ``worldbank-indicator`` source for the Energy → Renewable Share dataset.

The World Bank Indicators API is keyless but returns a two-element envelope
(``[metadata, [records]]``) with a nested ``country`` object and page/pages
paging — a shape no generic adapter covers. This ~1-screen :class:`Source` maps
each indicator to one schema column and emits flat ``{country, iso3, year,
<column>}`` rows; the ``join`` step later merges the per-indicator rows by
``(iso3, year)``. No secret is required.
"""

from __future__ import annotations

from typing import Iterable

from datavibes.context import FetchContext
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

WORLD_BANK_URL = "https://api.worldbank.org/v2/country/all/indicator/{indicator}"
MAX_PAGES = 50


@register_source("worldbank-indicator")
class WorldBankIndicatorSource(Source):
    """Fetch one or more World Bank indicators → flat country-year rows."""

    def __init__(
        self,
        indicators: dict[str, str] | None = None,
        date_range: str = "2000:2024",
        per_page: int = 20000,
    ):
        # ``indicators`` maps a World Bank indicator id → the schema column it feeds.
        self.indicators = indicators or {}
        self.date_range = date_range
        self.per_page = per_page

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        records: list[dict] = []
        for indicator, column in self.indicators.items():
            records.extend(self._fetch_indicator(ctx, indicator, column))
        return records

    def _fetch_indicator(
        self, ctx: FetchContext, indicator: str, column: str
    ) -> list[dict]:
        url = WORLD_BANK_URL.format(indicator=indicator)
        collected: list[dict] = []
        page = 1
        for _ in range(MAX_PAGES):
            params = {
                "format": "json",
                "per_page": self.per_page,
                "date": self.date_range,
                "page": page,
            }
            response = request_with_retry(
                ctx.http, url, params=params, headers={}, settings=ctx.http_settings
            )
            body = response.json()
            if not isinstance(body, list) or len(body) < 2:
                break
            meta, results = body[0], body[1] or []
            for item in results:
                row = self._map_result(item, column)
                if row is not None:
                    collected.append(row)
            pages = int((meta or {}).get("pages", 1) or 1)
            if page >= pages:
                break
            page += 1
        return collected

    @staticmethod
    def _map_result(item: dict, column: str) -> dict | None:
        iso3 = (item.get("countryiso3code") or "").strip()
        value = item.get("value")
        year = str(item.get("date", "")).strip()
        if not iso3 or value is None or not year:
            return None
        country = item.get("country") or {}
        name = country.get("value") if isinstance(country, dict) else str(country)
        return {"country": name, "iso3": iso3, "year": year, column: float(value)}
