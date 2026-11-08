"""``bis-series`` — BIS statistics bulk files → annual country-year rows (keyless).

The BIS publishes each dataflow as one flat CSV in a zip
(``https://data.bis.org/static/bulk/<DATAFLOW>_csv_flat.zip``): ``WS_SPP`` holds
the selected residential property price **indices**, ``WS_DPP`` the detailed
series, some of them price **levels** per square metre. Every dimension column
is headed ``CODE:Label`` and every cell reads ``code: label``; ``filters`` match
on the code (``{VALUE: N, UNIT_MEASURE: "628"}``).

``series: {ISO3: {REF_AREA: FR, …, multiplier: 1000}}`` picks one series per
country (its filters are added to the shared ``filters``). Quarterly or monthly
observations are averaged per calendar year. ``basis_column`` + ``basis`` tag
every emitted row (e.g. ``observed``).
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import replace
from typing import Iterable, Mapping

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

BIS_BULK = "https://data.bis.org/static/bulk/{dataflow}_csv_flat.zip"
VALUE_HEADER = "OBS_VALUE"
TIME_HEADER = "TIME_PERIOD"


def annual_means(observations: Iterable[tuple[str, float]]) -> dict[int, float]:
    """``(period, value)`` with periods like ``2024``, ``2024-Q3`` or ``2024-07`` → yearly means."""
    by_year: dict[int, list[float]] = defaultdict(list)
    for period, value in observations:
        by_year[int(period[:4])].append(value)
    return {year: sum(values) / len(values) for year, values in sorted(by_year.items())}


@register_source("bis-series")
class BisSeriesSource(Source):
    def __init__(
        self,
        dataflow: str,
        series: Mapping[str, Mapping],
        value_column: str,
        filters: Mapping[str, str] | None = None,
        basis_column: str | None = None,
        basis: str = "observed",
        url: str | None = None,
        timeout_seconds: float = 120.0,
    ):
        if not dataflow or not value_column:
            raise ConfigError("bis-series requires 'dataflow' and 'value_column'")
        if not series:
            raise ConfigError("bis-series requires at least one entry in 'series'")
        for iso3, spec in series.items():
            if not isinstance(spec, Mapping) or "REF_AREA" not in spec:
                raise ConfigError(f"bis-series: series.{iso3} needs a 'REF_AREA'")
        self.dataflow = dataflow
        self.series = {iso3: dict(spec) for iso3, spec in series.items()}
        self.value_column = value_column
        self.filters = {key: str(value) for key, value in (filters or {}).items()}
        self.basis_column = basis_column
        self.basis = basis
        self.url = url or BIS_BULK.format(dataflow=dataflow)
        self.timeout_seconds = float(timeout_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        settings = replace(ctx.http_settings, timeout_seconds=self.timeout_seconds)
        payload = request_with_retry(ctx.http, self.url, settings=settings).content
        wanted = {
            iso3: {**self.filters, **{k: str(v) for k, v in spec.items() if k != "multiplier"}}
            for iso3, spec in self.series.items()
        }
        observations: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for record in _flat_rows(payload):
            period, raw = record.get(TIME_HEADER, ""), record.get(VALUE_HEADER, "")
            if not period or raw in ("", "NaN"):
                continue
            for iso3, conditions in wanted.items():
                if all(record.get(key) == code for key, code in conditions.items()):
                    try:
                        observations[iso3].append((period, float(raw)))
                    except ValueError:
                        pass
        rows: list[dict] = []
        for iso3, spec in self.series.items():
            multiplier = float(spec.get("multiplier", 1))
            for year, value in annual_means(observations.get(iso3, [])).items():
                row = {"iso3": iso3, "year": year, self.value_column: value * multiplier}
                if self.basis_column:
                    row[self.basis_column] = self.basis
                rows.append(row)
        return rows


def _flat_rows(payload: bytes):
    """Rows of the bulk CSV with headers and cells reduced to their codes."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as error:
        raise SourceFetchError(f"bis-series: not a zip archive ({error})") from error
    members = [name for name in archive.namelist() if name.endswith(".csv")]
    if not members:
        raise SourceFetchError("bis-series: no CSV member in the archive")
    csv.field_size_limit(1 << 30)
    with archive.open(members[0]) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        headers = [header.split(":", 1)[0] for header in next(reader)]
        for cells in reader:
            yield {header: cell.split(":", 1)[0].strip() if header not in (VALUE_HEADER, TIME_HEADER) else cell
                   for header, cell in zip(headers, cells)}
