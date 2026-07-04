"""Bespoke ``ncei-climate`` source for the US Regional Weather dataset.

This is the *only* hand-written code this dataset needs. Everything else is
declared in ``dataset.yaml``. The NCEI Climate Data Online (CDO) v2 API needs a
token header and per-station paging that no generic adapter covers, so it earns
a ~1-screen custom :class:`Source` registered through the registry — the SDK is
never edited.

Secrets come from the environment (``NCDC_WEB_SERVICE_TOKEN``, with ``NCEI_TOKEN``
accepted as an alias); nothing is committed.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

NCEI_DATA_URL = "https://www.ncei.noaa.gov/cdo-web/api/v2/data"
# Canonical name is the one NOAA/NCDC issues the token under; NCEI_TOKEN is a
# backward-compatible alias. First non-empty wins.
TOKEN_ENV_VARS = ("NCDC_WEB_SERVICE_TOKEN", "NCEI_TOKEN")
PAGE_LIMIT = 1000
MAX_PAGES = 50
# CDO v2 rejects daily ranges longer than one year (HTTP 400), so requests are
# split into inclusive windows of at most this many days.
MAX_RANGE_DAYS = 365
TENTHS = 10.0

# GHCND datatypes → the schema column they feed.
_TEMPERATURE_TYPES = {"TMAX", "TMIN"}
_PRECIP_TYPES = {"PRCP"}


@register_source("ncei-climate")
class NceiClimateSource(Source):
    """Fetch daily GHCND observations per station and shape them to the schema."""

    def __init__(
        self,
        dataset: str = "GHCND",
        stations: list[str] | None = None,
        metrics: list[str] | None = None,
        lookback_days: int = 400,
    ):
        self.dataset = dataset
        self.stations = stations or []
        self.metrics = metrics or ["TMAX", "TMIN", "PRCP"]
        self.lookback_days = lookback_days

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        end = ctx.clock.now().date()
        start = end - timedelta(days=self.lookback_days)
        headers = {"token": _resolve_token()}

        records: list[dict] = []
        for window_start, window_end in _date_windows(start, end, MAX_RANGE_DAYS):
            base_params = {
                "datasetid": self.dataset,
                "datatypeid": self.metrics,
                "startdate": window_start.isoformat(),
                "enddate": window_end.isoformat(),
                "limit": PAGE_LIMIT,
            }
            for station in self.stations:
                records.extend(self._fetch_station(ctx, station, headers, base_params))
        return records

    def _fetch_station(
        self, ctx: FetchContext, station: str, headers: dict, base_params: dict
    ) -> list[dict]:
        collected: list[dict] = []
        offset = 1
        # CDO v2 wants a namespaced station id (``GHCND:USW00094728``); accept a
        # bare id in config and prefix it with the dataset here.
        station_id = station if ":" in station else f"{self.dataset}:{station}"
        for _page in range(MAX_PAGES):
            params = dict(base_params, stationid=station_id, offset=offset)
            response = request_with_retry(
                ctx.http,
                NCEI_DATA_URL,
                params=params,
                headers=headers,
                settings=ctx.http_settings,
            )
            body = response.json()
            results = body.get("results") or []
            if not results:
                break
            collected.extend(self._map_result(station, item) for item in results)
            collected = [record for record in collected if record is not None]
            count = _result_count(body)
            offset += PAGE_LIMIT
            if offset > count:
                break
        return [record for record in collected if record]

    @staticmethod
    def _map_result(region: str, item: dict) -> dict | None:
        datatype = item.get("datatype")
        raw_value = item.get("value")
        observed = str(item.get("date", ""))[:10]
        if raw_value is None or not observed:
            return None
        value = float(raw_value) / TENTHS
        if datatype in _TEMPERATURE_TYPES:
            return {"region": region, "date": observed, "temp_mean_c": value}
        if datatype in _PRECIP_TYPES:
            return {"region": region, "date": observed, "precip_mm": value}
        return None


def _date_windows(start, end, max_span_days: int):
    """Yield contiguous inclusive (start, end) windows of <= ``max_span_days``.

    CDO v2 caps a daily query at one year; a longer requested range is split
    into back-to-back windows so every request stays within the limit.
    """
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=max_span_days - 1))
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _resolve_token() -> str:
    """First non-empty token across the accepted env-var names."""
    for name in TOKEN_ENV_VARS:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


def _result_count(body: dict) -> int:
    metadata = body.get("metadata") or {}
    resultset = metadata.get("resultset") or {}
    return int(resultset.get("count", 0))
