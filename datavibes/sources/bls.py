"""``bls-series`` — US Bureau of Labor Statistics time series, keyless (API v1).

The v1 API takes a POST of ``{"seriesid": [...], "startyear", "endyear"}`` and
serves at most 10 years per request without a key, so the source walks the
range in 10-year windows. Monthly observations (``M01``…``M12``) are averaged
per calendar year; the annual-average period ``M13`` is ignored so every year
is computed the same way.

``series: {ISO3: SERIES_ID}`` — e.g. ``{USA: CUUR0000SETA01}`` (CPI-U, new
vehicles, 1953→). Unauthenticated callers get a small daily quota (25 requests),
so keep ``start_year`` no earlier than the series needs.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Iterable, Mapping

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source

BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
WINDOW_YEARS = 10


def year_windows(start: int, end: int, size: int = WINDOW_YEARS) -> list[tuple[int, int]]:
    """``[start, end]`` split into consecutive windows of at most ``size`` years."""
    return [(first, min(first + size - 1, end)) for first in range(start, end + 1, size)]


@register_source("bls-series")
class BlsSeriesSource(Source):
    def __init__(self, series: Mapping[str, str], value_column: str, start_year: int = 1953,
                 end_year: int | None = None, url: str = BLS_URL, timeout_seconds: float = 60.0,
                 retries: int = 3):
        if not series or not value_column:
            raise ConfigError("bls-series requires 'series' ({ISO3: series id}) and 'value_column'")
        self.series = dict(series)
        self.value_column = value_column
        self.start_year = int(start_year)
        self.end_year = int(end_year) if end_year else None
        self.url = url
        self.timeout_seconds = float(timeout_seconds)
        self.retries = max(1, int(retries))

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        end = self.end_year or (ctx.clock.now().year if ctx.clock else time.gmtime().tm_year)
        monthly: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        for first, last in year_windows(self.start_year, end):
            payload = {"seriesid": list(self.series.values()), "startyear": str(first), "endyear": str(last)}
            for block in self._post(ctx, payload).get("Results", {}).get("series", []):
                for point in block.get("data", []):
                    period = point.get("period", "")
                    if not (period.startswith("M") and period != "M13"):
                        continue
                    try:
                        monthly[block.get("seriesID")][int(point["year"])].append(float(point["value"]))
                    except (KeyError, TypeError, ValueError):
                        continue
        rows: list[dict] = []
        for iso3, series_id in self.series.items():
            for year, values in sorted(monthly.get(series_id, {}).items()):
                rows.append({"iso3": iso3, "year": year, self.value_column: sum(values) / len(values)})
        return rows

    def _post(self, ctx: FetchContext, payload: dict) -> dict:
        if ctx.http is None:
            raise SourceFetchError(f"no HTTP session injected for POST {self.url}")
        last = None
        for attempt in range(self.retries):
            response = ctx.http.post(self.url, json=payload, timeout=self.timeout_seconds)
            last = getattr(response, "status_code", 200)
            if 200 <= last < 300:
                body = response.json()
                if body.get("status") != "REQUEST_SUCCEEDED":
                    raise SourceFetchError(f"bls-series: {body.get('status')} {body.get('message')}")
                return body
            if last >= 500 or last == 429:
                time.sleep(ctx.http_settings.backoff_seconds * (attempt + 1))
                continue
            break
        raise SourceFetchError(f"POST {self.url} returned status {last}")
