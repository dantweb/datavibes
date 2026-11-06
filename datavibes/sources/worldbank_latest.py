"""``worldbank-latest`` — World Bank WDI API v2 (free, no key).

Fetches one or more indicators for every economy, follows the API's paging,
drops regional/income aggregates, and merges the indicators into one record
per country (keyed by ISO3). Every mapped column is present on every record
(``None`` when the World Bank has no value) so the schema's ``validate`` step
sees a uniform shape.

Built in rather than dataset-local because more than one dataset uses it.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

WORLD_BANK_API = "https://api.worldbank.org/v2"
AGGREGATES_REGION = "Aggregates"


@register_source("worldbank-latest")
class WorldBankLatestSource(Source):
    """``indicators: {CODE: {value: <column>, year: <column>}}`` → one row per country."""

    def __init__(
        self,
        indicators: dict,
        most_recent_non_empty: bool = True,
        exclude_aggregates: bool = True,
        base_url: str = WORLD_BANK_API,
        per_page: int = 1000,
        max_pages: int = 50,
    ):
        if not indicators:
            raise ConfigError("worldbank-latest requires at least one indicator")
        for code, mapping in indicators.items():
            if not isinstance(mapping, dict) or not mapping.get("value"):
                raise ConfigError(f"worldbank-latest: '{code}' needs a 'value' column")
        self.indicators = indicators
        self.most_recent_non_empty = most_recent_non_empty
        self.exclude_aggregates = exclude_aggregates
        self.base_url = base_url.rstrip("/")
        self.per_page = per_page
        self.max_pages = max_pages

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        aggregates = self._aggregate_codes(ctx) if self.exclude_aggregates else set()
        merged: dict[str, dict] = {}
        for code, mapping in self.indicators.items():
            params = {"format": "json", "per_page": self.per_page}
            if self.most_recent_non_empty:
                params["mrnev"] = 1
            url = f"{self.base_url}/country/all/indicator/{code}"
            for observation in self._pages(ctx, url, params):
                iso3 = (observation.get("countryiso3code") or "").strip()
                if not iso3 or iso3 in aggregates or observation.get("value") is None:
                    continue
                record = merged.setdefault(iso3, self._empty_record(iso3, observation))
                record[mapping["value"]] = observation["value"]
                if mapping.get("year"):
                    record[mapping["year"]] = int(observation["date"])
        return [merged[iso3] for iso3 in sorted(merged)]

    def _empty_record(self, iso3: str, observation: dict) -> dict:
        record = {"iso3": iso3, "country": (observation.get("country") or {}).get("value", "")}
        for mapping in self.indicators.values():
            record[mapping["value"]] = None
            if mapping.get("year"):
                record[mapping["year"]] = None
        return record

    def _aggregate_codes(self, ctx: FetchContext) -> set[str]:
        countries = self._pages(
            ctx, f"{self.base_url}/country", {"format": "json", "per_page": 400}
        )
        return {
            country["id"]
            for country in countries
            if ((country.get("region") or {}).get("value") or "").strip() == AGGREGATES_REGION
        }

    def _pages(self, ctx: FetchContext, url: str, params: dict) -> Iterator[dict]:
        page = 1
        while page <= self.max_pages:
            response = request_with_retry(
                ctx.http, url, params={**params, "page": page}, settings=ctx.http_settings
            )
            body = response.json()
            if not isinstance(body, list) or not body or not isinstance(body[0], dict) or "message" in body[0]:
                raise SourceFetchError(f"World Bank API error for {url}: {body!r:.300}")
            yield from (body[1] or []) if len(body) > 1 else []
            if page >= int(body[0].get("pages") or 1):
                return
            page += 1
