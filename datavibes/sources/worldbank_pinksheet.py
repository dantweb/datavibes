"""``worldbank-pinksheet`` — World Bank Commodity Price Data ("Pink Sheet"), annual.

One row per year with the requested commodities' nominal US-dollar prices,
read from the ``Annual Prices (Nominal)`` sheet of ``CMO-Historical-Data-Annual.xlsx``
(1960→today). The file's URL embeds a release hash that changes every month,
so by default the source reads the commodity-markets page and follows the
current link; ``url`` pins one file instead.

The rows carry no country: broadcast them onto country-year rows with
``lookup: {from_source: worldbank-pinksheet, on: year, …}``.
``openpyxl`` is optional (``pip install 'datavibes[xlsx]'``).
"""

from __future__ import annotations

import io
import re
from dataclasses import replace
from typing import Iterable, Mapping

from datavibes.context import FetchContext
from datavibes.errors import ConfigError, DatavibesError, SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

PAGE_URL = "https://www.worldbank.org/en/research/commodity-markets"
LINK_PATTERN = r'https://thedocs\.worldbank\.org/[^"\']+/CMO-Historical-Data-Annual\.xlsx'
SHEET = "Annual Prices (Nominal)"


def parse_annual_sheet(rows: list[tuple], commodities: Mapping[str, str]) -> list[dict]:
    """The sheet's rows → ``[{year, <column>: price}]`` for the named commodities.

    The header row is the one naming the commodities; data rows start with a
    year. ``…`` or blank cells (no quote) become ``None``.
    """
    header_index = next((i for i, row in enumerate(rows)
                         if row and any(cell in commodities for cell in row)), None)
    if header_index is None:
        raise SourceFetchError(f"worldbank-pinksheet: none of {sorted(commodities)} found in the sheet")
    header = rows[header_index]
    missing = [name for name in commodities if name not in header]
    if missing:
        raise SourceFetchError(f"worldbank-pinksheet: commodities not in the sheet: {missing}")
    positions = {column: header.index(name) for name, column in commodities.items()}
    out: list[dict] = []
    for row in rows[header_index + 1:]:
        if not row or not re.fullmatch(r"\d{4}", str(row[0]).strip()):
            continue
        record: dict = {"year": int(str(row[0]).strip())}
        for column, position in positions.items():
            value = row[position] if position < len(row) else None
            record[column] = float(value) if isinstance(value, (int, float)) else None
        out.append(record)
    return out


@register_source("worldbank-pinksheet")
class WorldBankPinkSheetSource(Source):
    def __init__(self, commodities: Mapping[str, str], url: str | None = None,
                 page_url: str = PAGE_URL, timeout_seconds: float = 120.0):
        if not commodities:
            raise ConfigError("worldbank-pinksheet requires 'commodities' ({sheet name: column})")
        self.commodities = dict(commodities)
        self.url = url
        self.page_url = page_url
        self.timeout_seconds = float(timeout_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        try:
            import openpyxl  # type: ignore
        except ImportError as exc:
            raise DatavibesError("worldbank-pinksheet requires the optional 'openpyxl' dependency; "
                                 "install it with: pip install 'datavibes[xlsx]'") from exc
        settings = replace(ctx.http_settings, timeout_seconds=self.timeout_seconds)
        url = self.url or self._current_link(ctx, settings)
        payload = request_with_retry(ctx.http, url, settings=settings).content
        workbook = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        if SHEET not in workbook.sheetnames:
            raise SourceFetchError(f"worldbank-pinksheet: no '{SHEET}' sheet in {url}")
        return parse_annual_sheet(list(workbook[SHEET].iter_rows(values_only=True)), self.commodities)

    def _current_link(self, ctx: FetchContext, settings) -> str:
        page = request_with_retry(ctx.http, self.page_url, settings=settings).text
        match = re.search(LINK_PATTERN, page)
        if not match:
            raise SourceFetchError(f"worldbank-pinksheet: no annual data link on {self.page_url}")
        return match.group(0)
