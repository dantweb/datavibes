"""``faostat-prices`` — FAOSTAT producer prices for one item, harmonised over 1966→today.

FAOSTAT publishes producer prices in two bulk files:

* **current** (``Prices``, 1991→): ``LCU/tonne``, ``SLC/tonne`` (the price in
  today's currency unit) and a producer-price **index** that often runs a year or
  more past the last absolute price;
* **archive** (``PricesArchive``, 1966–1990): ``LCU/tonne`` only, in whatever
  currency the country used then (francs, Deutschmarks, lira, australes, rubles …).

This source turns both into one series per country, in today's currency:

1. :func:`rebase_archive` — archive LCU × (SLC ÷ LCU of the first current year),
   so the conversion factor comes from FAO's own numbers, never a hard-coded table;
2. :func:`extend_with_index` — a year with an index but no absolute price is the
   nearest observed price × index(year) ÷ index(anchor);
3. ``archive_rescale`` fixes a unit switch *inside* the archive — archive years
   ``before`` a year (Mexico: old pesos until 1981) or ``from`` a year (Poland:
   new złoty already in 1989–1990) are multiplied by ``factor`` first;
4. ``archive_exclude`` drops an area's whole archive series (``ISO3: reason``) or
   only its early years (``ISO3: {before: year, reason}`` — e.g. values rounded
   to too few digits), always with a stated reason;
5. ``index_exclude`` (``ISO3: reason``) switches the index extension off for a
   country whose index can't be trusted over long chains (Iran: one observed
   price in 34 years).

Each output row carries ``price_basis``: ``observed`` | ``archive-rebased`` |
``index-extended``. The harmonisation functions are pure; the class only
downloads, filters and composes them.
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from dataclasses import replace
from typing import Iterable, Iterator, Mapping

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.processing.functions import extend_with_index
from datavibes.sources.http_client import request_with_retry

FAOSTAT_BULK = "https://bulks-faostat.fao.org/production"
CURRENT_URL = f"{FAOSTAT_BULK}/Prices_E_All_Data_(Normalized).zip"
ARCHIVE_URL = f"{FAOSTAT_BULK}/PricesArchive_E_All_Data_(Normalized).zip"
DEFAULT_TIMEOUT_SECONDS = 120.0

LCU = "Producer Price (LCU/tonne)"
SLC = "Producer Price (SLC/tonne)"
INDEX_PREFIX = "Producer Price Index"
ANNUAL = "Annual value"

OBSERVED = "observed"
ARCHIVE_REBASED = "archive-rebased"
INDEX_EXTENDED = "index-extended"

Series = dict[int, float]


# ------------------------------------------------------------- pure harmonising
def rebase_factor(current_lcu: Series, current_slc: Series) -> float | None:
    """SLC ÷ LCU in the first current year that has both (``None`` if none does)."""
    for year in sorted(set(current_lcu) & set(current_slc)):
        if current_lcu[year]:
            return current_slc[year] / current_lcu[year]
    return None


def rescale_before(series: Series, before: int, factor: float) -> Series:
    """Years before ``before`` multiplied by ``factor`` (a mid-series currency switch)."""
    return {year: value * factor if year < before else value for year, value in series.items()}


def rescale_from(series: Series, since: int, factor: float) -> Series:
    """Years from ``since`` on multiplied by ``factor`` (a switch that came early)."""
    return {year: value * factor if year >= since else value for year, value in series.items()}


def rebase_archive(archive_lcu: Series, factor: float, before: int) -> Series:
    """Archive prices strictly before ``before`` converted into today's unit."""
    return {year: value * factor for year, value in archive_lcu.items() if year < before}


def harmonise(
    current_lcu: Series,
    current_slc: Series,
    current_index: Series,
    archive_lcu: Series,
    use_archive: bool = True,
    archive_rescale: Mapping | None = None,
    use_index: bool = True,
) -> dict[int, tuple[float, str]]:
    """One ``{year: (price in today's unit, basis)}`` series from the four FAO inputs."""
    if archive_rescale:
        factor = float(archive_rescale["factor"])
        if "before" in archive_rescale:
            archive_lcu = rescale_before(archive_lcu, int(archive_rescale["before"]), factor)
        else:
            archive_lcu = rescale_from(archive_lcu, int(archive_rescale["from"]), factor)
    series: dict[int, tuple[float, str]] = {
        year: (value, OBSERVED) for year, value in current_slc.items()
    }
    factor = rebase_factor(current_lcu, current_slc)
    if use_archive and factor is not None and current_slc:
        first_current = min(current_slc)
        for year, value in rebase_archive(archive_lcu, factor, first_current).items():
            series[year] = (value, ARCHIVE_REBASED)
    for year, value in (extend_with_index(current_slc, current_index) if use_index else {}).items():
        series.setdefault(year, (value, INDEX_EXTENDED))
    return dict(sorted(series.items()))


# --------------------------------------------------------------------- source
@register_source("faostat-prices")
class FaostatPricesSource(Source):
    """``item`` + ``areas: {ISO3: {label, names, archive_names}}`` → country-year prices.

    ``names`` are FAO area names in the current file; ``archive_names`` (default:
    the same) in the archive — they differ where a country was renamed or
    re-bordered (``USSR`` → ``Russian Federation``, ``China`` → ``China, mainland``).
    """

    def __init__(
        self,
        item: str,
        areas: Mapping[str, Mapping],
        value_column: str = "price_slc_per_tonne",
        basis_column: str = "price_basis",
        archive_exclude: Mapping[str, object] | None = None,
        archive_rescale: Mapping[str, Mapping] | None = None,
        index_exclude: Mapping[str, str] | None = None,
        current_url: str = CURRENT_URL,
        archive_url: str | None = ARCHIVE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if not item:
            raise ConfigError("faostat-prices requires an 'item'")
        if not areas:
            raise ConfigError("faostat-prices requires at least one area")
        self.current_area_of: dict[str, str] = {}
        self.archive_area_of: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        for iso3, spec in areas.items():
            names = (spec or {}).get("names") or []
            if not names:
                raise ConfigError(f"faostat-prices: area '{iso3}' needs FAO 'names'")
            self.labels[iso3] = spec.get("label") or iso3
            for name in names:
                self.current_area_of[name] = iso3
            for name in spec.get("archive_names") or names:
                self.archive_area_of[name] = iso3
        self.item = item
        self.value_column = value_column
        self.basis_column = basis_column
        self.archive_exclude = dict(archive_exclude or {})
        self.archive_rescale = dict(archive_rescale or {})
        self.index_exclude = dict(index_exclude or {})
        for iso3, spec in self.archive_rescale.items():
            if (not isinstance(spec, Mapping) or "factor" not in spec
                    or ("before" in spec) == ("from" in spec)):
                raise ConfigError(
                    f"faostat-prices: archive_rescale.{iso3} needs 'factor' and exactly one of 'before'/'from'")
        for iso3, spec in self.archive_exclude.items():
            if isinstance(spec, Mapping) and "before" not in spec:
                raise ConfigError(f"faostat-prices: archive_exclude.{iso3} needs 'before' (or a plain reason)")
        self.current_url = current_url
        self.archive_url = archive_url
        self.timeout_seconds = float(timeout_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        current = self._collect(self._download(ctx, self.current_url), self.current_area_of)
        archive = (self._collect(self._download(ctx, self.archive_url), self.archive_area_of)
                   if self.archive_url else {})
        for iso3, spec in self.archive_exclude.items():
            if isinstance(spec, Mapping):
                print(f"warning: faostat-prices: archive years of {iso3} before {spec['before']} skipped — "
                      f"{spec.get('reason', 'excluded')}", file=sys.stderr)
            else:
                print(f"warning: faostat-prices: archive series for {iso3} skipped — {spec}", file=sys.stderr)
        for iso3, reason in self.index_exclude.items():
            print(f"warning: faostat-prices: no index extension for {iso3} — {reason}", file=sys.stderr)
        rows: list[dict] = []
        for iso3 in self.labels:
            elements = current.get(iso3, {})
            archive_lcu = archive.get(iso3, {}).get(LCU, {})
            exclusion = self.archive_exclude.get(iso3)
            if isinstance(exclusion, Mapping):
                archive_lcu = {year: value for year, value in archive_lcu.items()
                               if year >= int(exclusion["before"])}
            series = harmonise(
                elements.get(LCU, {}), elements.get(SLC, {}), elements.get(INDEX_PREFIX, {}),
                archive_lcu,
                use_archive=exclusion is None or isinstance(exclusion, Mapping),
                archive_rescale=self.archive_rescale.get(iso3),
                use_index=iso3 not in self.index_exclude,
            )
            for year, (value, basis) in series.items():
                rows.append({"iso3": iso3, "country": self.labels[iso3], "year": year,
                             self.value_column: value, self.basis_column: basis})
        return rows

    # ------------------------------------------------------------ internals
    def _download(self, ctx: FetchContext, url: str) -> bytes:
        settings = replace(ctx.http_settings, timeout_seconds=self.timeout_seconds)
        return request_with_retry(ctx.http, url, settings=settings).content

    def _collect(self, payload: bytes, area_of: Mapping[str, str]) -> dict[str, dict[str, Series]]:
        """``{iso3: {element: {year: value}}}`` for the item, annual values only."""
        collected: dict[str, dict[str, Series]] = {}
        for record in _normalized_rows(payload):
            iso3 = area_of.get(record.get("Area", ""))
            if iso3 is None or record.get("Item") != self.item:
                continue
            if record.get("Months", ANNUAL) != ANNUAL:
                continue
            element = record.get("Element", "")
            if element.startswith(INDEX_PREFIX):
                element = INDEX_PREFIX
            elif element not in (LCU, SLC):
                continue
            try:
                year, value = int(record["Year"]), float(record["Value"])
            except (KeyError, TypeError, ValueError):
                continue
            collected.setdefault(iso3, {}).setdefault(element, {}).setdefault(year, value)
        return collected


def _normalized_rows(payload: bytes) -> Iterator[dict]:
    """Stream the ``*_All_Data_(Normalized).csv`` member of a FAOSTAT bulk zip."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as error:
        raise SourceFetchError(f"faostat-prices: not a zip archive ({error})") from error
    members = [name for name in archive.namelist() if name.endswith("(Normalized).csv")]
    if not members:
        raise SourceFetchError("faostat-prices: no '(Normalized).csv' member in the archive")
    with archive.open(members[0]) as handle:
        yield from csv.DictReader(io.TextIOWrapper(handle, encoding="latin-1", newline=""))
