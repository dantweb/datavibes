"""``ilostat`` — one ILOSTAT indicator slice → country-year rows (keyless).

ILOSTAT's rplumber API returns a CSV for an indicator id
(``EAR_EMTA_SEX_EDU_NB_A`` = average monthly earnings by sex and education, in
local currency), filtered server-side by ``ref_area`` and ``sex``. The remaining
dimensions (``classif1`` = the education level, …) are filtered client-side
with ``filters``.

One country-year often has several surveys behind it (``source`` = a labour
force survey, an establishment survey, …). Mixing surveys from year to year
creates jumps (Italy: an establishment survey reads ~2× the labour force
survey), so :func:`pick_one_per_year` keeps each country on the survey with the
most years; ``fill_from_other_surveys: true`` lets the next-best fill the years
that survey lacks. The chosen survey goes to ``source_column`` when declared.
``exclude_before: {ISO3: {year, reason}}`` drops a country's implausible early
years with a stated reason.
"""

from __future__ import annotations

import csv
import io
import sys
from collections import defaultdict
from dataclasses import replace
from typing import Iterable, Mapping, Sequence

from datavibes.context import FetchContext
from datavibes.errors import ConfigError
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

ILOSTAT_URL = "https://rplumber.ilo.org/data/indicator/"
SERVER_FILTERS = ("sex",)


def pick_one_per_year(
    observations: Sequence[tuple[str, int, float]], fill: bool = False
) -> dict[int, tuple[float, str]]:
    """``(source, year, value)`` → ``{year: (value, source)}`` from the longest source
    (ties: alphabetical); with ``fill``, shorter sources fill its missing years."""
    by_source: dict[str, dict[int, float]] = defaultdict(dict)
    for source, year, value in observations:
        by_source[source].setdefault(year, value)
    ranked = sorted(by_source, key=lambda source: (-len(by_source[source]), source))
    chosen: dict[int, tuple[float, str]] = {}
    for source in ranked if fill else ranked[:1]:
        for year, value in by_source[source].items():
            chosen.setdefault(year, (value, source))
    return dict(sorted(chosen.items()))


@register_source("ilostat")
class IlostatSource(Source):
    def __init__(
        self,
        indicator: str,
        ref_areas: Sequence[str],
        value_column: str,
        filters: Mapping[str, str] | None = None,
        source_column: str | None = None,
        fill_from_other_surveys: bool = False,
        exclude_before: Mapping[str, Mapping] | None = None,
        base_url: str = ILOSTAT_URL,
        timeout_seconds: float = 120.0,
    ):
        if not indicator or not value_column:
            raise ConfigError("ilostat requires 'indicator' and 'value_column'")
        if not ref_areas:
            raise ConfigError("ilostat requires at least one ref_area")
        self.indicator = indicator
        self.ref_areas = list(ref_areas)
        self.value_column = value_column
        self.filters = dict(filters or {})
        self.source_column = source_column
        self.fill = bool(fill_from_other_surveys)
        self.exclude_before = dict(exclude_before or {})
        for iso3, spec in self.exclude_before.items():
            if not isinstance(spec, Mapping) or "year" not in spec:
                raise ConfigError(f"ilostat: exclude_before.{iso3} needs a 'year'")
        self.base_url = base_url
        self.timeout_seconds = float(timeout_seconds)

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        params = {"id": self.indicator, "ref_area": "+".join(self.ref_areas), "format": ".csv"}
        params.update({key: self.filters[key] for key in SERVER_FILTERS if key in self.filters})
        settings = replace(ctx.http_settings, timeout_seconds=self.timeout_seconds)
        response = request_with_retry(ctx.http, self.base_url, params=params, settings=settings)
        observations: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
        for record in csv.DictReader(io.StringIO(response.text.lstrip("﻿"))):
            if any(record.get(key) != value for key, value in self.filters.items()):
                continue
            try:
                year, value = int(str(record["time"])[:4]), float(record["obs_value"])
            except (KeyError, TypeError, ValueError):
                continue
            observations[record.get("ref_area", "")].append((record.get("source", ""), year, value))
        rows: list[dict] = []
        for iso3, spec in self.exclude_before.items():
            print(f"warning: ilostat: {iso3} before {spec['year']} skipped — {spec.get('reason', 'excluded')}",
                  file=sys.stderr)
            observations[iso3] = [obs for obs in observations.get(iso3, []) if obs[1] >= int(spec["year"])]
        for iso3 in self.ref_areas:
            for year, (value, survey) in pick_one_per_year(observations.get(iso3, []), self.fill).items():
                row = {"iso3": iso3, "year": year, self.value_column: value}
                if self.source_column:
                    row[self.source_column] = survey
                rows.append(row)
        return rows
