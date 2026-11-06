# Creating datasets

A dataset is **one folder with one file**: `datasets/<slug>/dataset.yaml`. The SDK
already handles fetching, snapshotting, transforming, validating and writing. You
**declare** what you want. Code is the rare exception: a small `sources.py` for an
API no built-in adapter covers (§9).

This guide builds up from a minimal dataset to maps. Every complete example
below is a working `dataset.yaml`; copy one into `datasets/<slug>/` and run it.
[reference.md](reference.md) lists every option of every building block.

---

## 1. The pipeline in one picture

```
 sources:  ──fetch──▶  raw snapshot  ──processing:──▶  rows  ──validate──▶  outputs:
 (APIs, CSV,           store/raw/<slug>/  (rename, filter,       schema    csv · json · parquet
  SPARQL, …)           <ts>.jsonl          join, derive, …)      check     svg-map · svg-dot-map
```

- **Sources only fetch.** Each yields flat records. A failing source contributes
  zero rows and a warning; it never crashes the run.
- **Processing steps are pure.** List in, list out, applied in the order you write them.
- **The schema is the contract.** It fixes which columns exist, their types and
  their order. `normalize` coerces types and drops every column the schema doesn't name.
- **Outputs write.** Every output of one run shares one timestamp.

---

## 2. Anatomy of `dataset.yaml`

```yaml
parameters:          # optional — tunable values, documented in one place (§6)
metadata:            # required — who/what/licence
schema:              # required — the output columns
sources:             # required — at least one
processing:          # optional — ordered steps; end with `validate`
outputs:             # optional — default: one CSV (config.yaml defaults.format)
charts:              # optional — report charts, see charts.md
```

### `metadata`

```yaml
metadata:
  slug: gdp-life-expectancy        # kebab-case; must match the folder name
  title: GDP vs Life Expectancy
  category: macro                  # free text; used by the "category" output layout
  license: "CC BY 4.0 (World Bank WDI)"   # the DATA's licence: you redistribute it
  update_frequency: annual         # how often the SOURCE publishes
  attribution: "World Bank World Development Indicators"
```

### `schema`

```yaml
schema:
  - { name: iso3,  dtype: str }
  - { name: year,  dtype: int }
  - { name: gdp_per_capita_usd, dtype: float, unit: "USD", nullable: true, description: "current US$" }
```

`dtype` is one of `str`, `int`, `float`, `bool`, `date`. A column that may be empty
**must** be `nullable: true`, otherwise `validate` fails the run (deliberately).

### Environment interpolation

Any string in `sources`, `processing` or `outputs` may use `${VAR}` or
`${VAR:-default}`. Secrets **always** come in this way (from `.env`); they are
never written into the file.

---

## 3. Example 1: the minimal dataset

```bash
datavibes new city-scores --category demo     # scaffolds the file below
datavibes validate city-scores && datavibes run city-scores
```

```yaml
# example: city-scores
metadata:
  slug: city-scores
  title: City Scores
  category: demo
  update_frequency: daily

schema:
  - { name: city,  dtype: str }
  - { name: score, dtype: int }

sources:
  - type: static                  # inline records: no network, always green
    records:
      - { city: Berlin, score: 7 }
      - { city: Lisbon, score: 9 }

processing:
  - normalize
  - validate
```

Start every dataset this way. Get the schema and outputs right with `static`
records, then swap in the real source.

---

## 4. Example 2: a public CSV, cleaned and derived

Our World in Data publishes plain CSVs with human-readable headers. `rename` maps
them to schema columns, `filter` drops aggregates, and `derive` adds
growth per country.

```yaml
# example: co2-growth
metadata:
  slug: co2-growth
  title: CO₂ Emissions — Year-on-Year Growth
  category: environment
  license: "CC BY 4.0 (Our World in Data)"
  update_frequency: annual
  attribution: "Our World in Data — Global Carbon Budget"

schema:
  - { name: country,     dtype: str }
  - { name: iso3,        dtype: str }
  - { name: year,        dtype: int }
  - { name: co2_tonnes,  dtype: float, unit: "t" }
  - { name: co2_yoy_pct, dtype: float, unit: "%", nullable: true }

sources:
  - type: http_csv
    url: https://ourworldindata.org/grapher/annual-co2-emissions-per-country.csv
    params: { csvType: full }

processing:
  - rename:
      columns: { Entity: country, Code: iso3, Year: year, "Annual CO₂ emissions": co2_tonnes }
  # Aggregates (World, continents) have an empty code: drop them before normalize.
  - filter: { all: [{ column: iso3, not_null: true }, { column: iso3, ne: "" }] }
  - normalize
  - filter: { when: { column: year, gte: 2000 } }
  - sort:   { by: [iso3, year] }                       # windowed helpers need time order
  - derive: { column: co2_yoy_pct, expr: "yoy(co2_tonnes)", by: [iso3] }   # per country
  - derive: { column: co2_yoy_pct, expr: "round_to(co2_yoy_pct, digits=2)" }
  - validate
```

**Things to notice**
- `rename` and `filter` on raw keys run **before** `normalize`, because
  `normalize` drops every key the schema doesn't know.
- `derive … by: [iso3]` runs the helper **within each country**, so growth never
  spans two countries.
- A `derive` may overwrite its own column (the rounding line).

---

## 5. Example 3: several indicators joined into one panel

The World Bank serves one indicator per request. `worldbank-indicator` emits one
row per country-year **per indicator**, and `join` merges them into one row per key.

```yaml
# example: gdp-life-expectancy
metadata:
  slug: gdp-life-expectancy
  title: GDP vs Life Expectancy
  category: macro
  license: "CC BY 4.0 (World Bank WDI)"
  update_frequency: annual
  attribution: "World Bank WDI (NY.GDP.PCAP.CD, SP.DYN.LE00.IN)"

schema:
  - { name: country,            dtype: str }
  - { name: iso3,               dtype: str }
  - { name: year,               dtype: int }
  - { name: gdp_per_capita_usd, dtype: float, nullable: true }
  - { name: life_expectancy,    dtype: float, nullable: true }
  - { name: income_tier,        dtype: str,   nullable: true }
  - { name: long_lived,         dtype: bool }

sources:
  - type: worldbank-indicator
    date_range: "2015:2024"
    indicators:
      NY.GDP.PCAP.CD: gdp_per_capita_usd
      SP.DYN.LE00.IN: life_expectancy

processing:
  - normalize
  - join:     { "on": [iso3, year] }        # quote "on": bare `on` is a YAML boolean!
  - filter:   { when: { column: life_expectancy, not_null: true }, reason: "no life-expectancy value" }
  - classify:
      column: income_tier
      value: gdp_per_capita_usd
      bins:
        - { label: low,    max: 1135 }
        - { label: middle, max: 13845 }
        - { label: high }                    # catch-all
  - flag:     { column: long_lived, when: { column: life_expectancy, gte: 80 } }
  - sort:     { by: [iso3, year] }
  - validate
```

**Two keys from one source vs. one key from another:** `join` *coalesces* rows
sharing a key into one row. To copy one row's columns onto **many** rows (a
country's figures onto each of its cities), use `lookup` instead (Example 5).

---

## 6. Parameters: make thresholds tunable

Gather tunable values at the top and reference them with a YAML anchor. A
value used inside a `derive` expression goes in `params:`, because anchors can't
be spliced into strings:

```yaml
parameters:
  # Override per run: HEAT_THRESHOLD=35 datavibes run <slug>
  heat_threshold: &heat_threshold "${HEAT_THRESHOLD:-30}"

processing:
  - derive: { column: hot_day, expr: "at_least(temp_max_c)", params: { threshold: *heat_threshold } }
```

The SDK ignores the `parameters:` block itself. It exists so readers find every
knob in one place.

---

## 7. Example 4: a country map (choropleth)

Add an `svg-map` output and pick a colour scale. This map colours countries by
population growth on the spectral scale. Growth can be **negative**, so
`normalize: linear` is used; `log` is only valid for strictly positive values.

```yaml
# example: population-growth-map
metadata:
  slug: population-growth-map
  title: Population Growth by Country
  category: colored-geostats
  license: "CC BY 4.0 (World Bank WDI); geometry public domain (Natural Earth)"
  update_frequency: annual
  attribution: &attribution "Data: World Bank WDI SP.POP.GROW, latest year per country"

schema:
  - { name: iso3,       dtype: str }
  - { name: country,    dtype: str }
  - { name: growth_pct, dtype: float, unit: "%", nullable: true }
  - { name: year,       dtype: int,   nullable: true }

sources:
  - type: worldbank-latest            # latest non-empty value per country
    indicators:
      SP.POP.GROW: { value: growth_pct, year: year }

processing:
  - normalize
  - derive: { column: growth_pct, expr: "round_to(growth_pct, digits=2)" }
  - validate

outputs:
  - csv
  - svg-map:
      geometry: natural-earth-admin0-110m
      scope: world
      exclude: [ATA]                                  # Antarctica
      key_column: iso3
      key_aliases: { SSD: SDS, PSE: PSX, XKX: KOS }   # World Bank → Natural Earth codes
      item_label: countries
      label_columns: [growth_pct, year]               # tooltip
      title: "Population growth (% per year)"
      footer: *attribution
      color_scale:
        type: spectral-density
        value_column: growth_pct
        value_label: "Population growth (%/year)"
        normalize: linear
        center: median
```

**Map checklist**
- After a run, open `<ts>.join.json`. `rows_not_drawn` lists data codes with no
  shape: add `key_aliases`, or accept it (micro-states aren't in the 110m geometry).
- `scope: region` with `region: { continent: Europe }` (or `{ iso3: [...] }`) plus
  `clip_bbox: [-25, 34, 45, 72]` gives a Europe map. French Guiana belongs to
  France's shape, so without `clip_bbox` the map would reach South America.
- For the men/women scheme, use `type: sex-ratio-bivariate` with a
  `ratio_column` (male share in %) and a `value_column` for intensity. See
  `datasets/world-population-density/`.

---

## 8. Example 5: a dot map (one dot per city)

`svg-dot-map` draws each row as a dot at its latitude/longitude; dot **area** is
proportional to `size_column`. This example lists European cities of 500,000+
people from Wikidata, coloured by density, with the country's name joined in by
`lookup`.

```yaml
# example: europe-big-cities
metadata:
  slug: europe-big-cities
  title: Europe's Big Cities by Density
  category: colored-geostats
  license: "CC0 (Wikidata); CC BY 4.0 (World Bank); geometry public domain (Natural Earth)"
  update_frequency: monthly
  attribution: &attribution "Cities: Wikidata · Countries: World Bank"

schema:
  - { name: wikidata_id,     dtype: str }
  - { name: city,            dtype: str }
  - { name: iso3,            dtype: str }
  - { name: country,         dtype: str,   nullable: true }
  - { name: latitude,        dtype: float }
  - { name: longitude,       dtype: float }
  - { name: population,      dtype: int }
  - { name: area_km2,        dtype: float, nullable: true }
  - { name: density_per_km2, dtype: float, nullable: true }

sources:
  - type: sparql                           # Wikidata by default
    strip_uri_prefix: true                 # http://…/entity/Q64 → Q64
    query: |
      SELECT ?city ?cityLabel ?iso3 ?population ?latitude ?longitude ?area_km2
      WHERE {
        {
          SELECT ?city (SAMPLE(?iso) AS ?iso3) (MAX(?pop) AS ?population)
                 (SAMPLE(?lat) AS ?latitude) (SAMPLE(?lon) AS ?longitude)
                 (MAX(?areaM2) / 1000000 AS ?area_km2)
          WHERE {
            ?city wdt:P31/wdt:P279* wd:Q515 ;
                  wdt:P1082 ?pop ;
                  wdt:P17 ?country ;
                  p:P625/psv:P625 [ wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon ] .
            ?country wdt:P30 wd:Q46 ; wdt:P298 ?iso .          # country in Europe
            OPTIONAL { ?city p:P2046/psn:P2046/wikibase:quantityAmount ?areaM2 . }
          }
          GROUP BY ?city
          HAVING (MAX(?pop) >= ${EUROPE_MIN_POPULATION:-500000})
        }
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". }
      }
  - type: worldbank-latest
    indicators:
      SP.POP.TOTL: { value: country_population }   # only needed for the country name

processing:
  - rename: { columns: { city: wikidata_id, cityLabel: city } }
  - lookup:                                        # before normalize: needs the _source tag
      from_source: worldbank-latest
      "on": iso3
      columns: { country: country }
  - normalize
  - derive: { column: density_per_km2, expr: "ratio(population, area_km2)" }
  - derive: { column: density_per_km2, expr: "null_outside(density_per_km2)", params: { low: 10, high: 60000 } }
  - filter: { when: { column: density_per_km2, not_null: true }, reason: "no usable density" }
  - derive: { column: density_per_km2, expr: "round_to(density_per_km2, digits=1)" }
  - sort:   { by: [iso3, city, wikidata_id] }      # SPARQL result order is not stable
  - validate

outputs:
  - csv
  - svg-dot-map:
      geometry: natural-earth-admin0-110m
      scope: world                           # draw every country as context…
      clip_bbox: [-25, 34, 45, 72]           # …but crop the canvas to Europe
      latitude_column: latitude
      longitude_column: longitude
      size_column: population
      size_label: city population
      size_legend: [500000, 1000000, 5000000]
      name_column: city
      item_label: cities
      label_columns: [country, population, density_per_km2]
      max_radius: 18
      title: "Europe's cities of 500,000+ by density"
      footer: *attribution
      basemap_color: "#d5d9de"
      color_scale:
        type: spectral-density
        value_column: density_per_km2
        value_label: "City density (people/km², log scale)"
        center: mean
        saturate_above: 10000
```

**Things to notice**
- `filter … reason:` feeds the map legend's **Coverage** block ("Cities shown:
  N of M · Not included: …: K") and `join.json` → `excluded`. Give every
  exclusion a reason.
- Wikidata's public endpoint stops queries at **60 s**. Group in a subquery and
  resolve labels outside it, as above. `FILTER NOT EXISTS` over large sets
  tends to time out.
- `null_outside` clears values a wrong unit made impossible. That matters for
  crowd-sourced data.
- **Dot maps: crop, don't filter, the basemap.** With `scope: region` +
  `region: { continent: Europe }` the basemap drops Turkey (Natural Earth puts
  it in Asia), yet Wikidata lists it in Europe, so Istanbul would float over
  blank space. `scope: world` + `clip_bbox` keeps neighbours visible as context.

---

## 9. When you need code: a custom source

When no built-in adapter fits the API (custom auth, odd paging, a response that
needs reshaping), write a small `datasets/<slug>/sources.py`. It is imported
automatically before the dataset loads:

```python
"""``open-meteo-now`` — current temperature for a list of places."""

from datavibes.context import FetchContext
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

URL = "https://api.open-meteo.com/v1/forecast"


@register_source("open-meteo-now")
class OpenMeteoNowSource(Source):
    def __init__(self, places: list[dict]):
        self.places = places                       # options come from dataset.yaml

    def fetch(self, ctx: FetchContext) -> list[dict]:
        rows = []
        for place in self.places:
            response = request_with_retry(         # retries, timeout, User-Agent
                ctx.http, URL,
                params={"latitude": place["lat"], "longitude": place["lon"], "current": "temperature_2m"},
                settings=ctx.http_settings,
            )
            rows.append({"place": place["name"], "temp_c": response.json()["current"]["temperature_2m"]})
        return rows
```

```yaml
sources:
  - type: open-meteo-now
    places:
      - { name: Berlin, lat: 52.52, lon: 13.41 }
      - { name: Lisbon, lat: 38.72, lon: -9.14 }
```

**Rules for adapters:** use the injected `ctx.http` (never `requests.get`), so tests
can mock it. Read the clock only through `ctx.clock`. Read secrets only from the
environment. Raise freely: the generator turns an exception into a warning and an
empty contribution. When a **second** dataset needs the same adapter, move it into
`datavibes/sources/` (as `worldbank-indicator` and `worldbank-latest` were).

---

## 10. Testing a dataset

Every shipped dataset has an offline test. The pattern
(`tests/test_dataset_world_population_density.py` is a complete example):

```python
from pathlib import Path
from datavibes import DatasetSDK
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse

DATASETS = Path(__file__).resolve().parents[1] / "datasets"

def responder(url, params, headers):                     # recorded-shape API bodies
    return FakeResponse(json_body=[{"page": 1, "pages": 1}, [...]])

def test_run_is_byte_stable(tmp_path, fixed_clock, make_session):
    def sdk(name):
        return DatasetSDK(root=DATASETS, clock=fixed_clock, store=FileStore(tmp_path / name),
                          env_file=tmp_path / "none.env", config_file=tmp_path / "none.yaml")
    first = sdk("a").run_outputs("my-dataset", http=make_session(responder))
    second = sdk("b").run_outputs("my-dataset", http=make_session(responder))
    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]
```

Golden files live in `tests/golden/`. `UPDATE_GOLDEN=1 pytest …` rewrites them;
review the diff before committing.

---

## 11. Checklist before you ship

- [ ] Folder name == `metadata.slug`; `license` + `attribution` reflect the **data**.
- [ ] Every possibly-empty column is `nullable: true`.
- [ ] Raw-key `rename`/`filter`/`lookup` steps come **before** `normalize`; `validate` is last.
- [ ] A `sort` gives deterministic row order (APIs and SPARQL don't guarantee one).
- [ ] Every `filter` that removes real entities has a `reason`.
- [ ] Bare YAML key `on` is quoted (`"on":`).
- [ ] `datavibes validate <slug>` passes; a live `run` produces sane row counts;
      maps: `join.json` reviewed.
- [ ] Tunables live in `parameters:` with `${VAR:-default}`; no secrets in the file.
- [ ] An offline test with a byte-stability check exists.
