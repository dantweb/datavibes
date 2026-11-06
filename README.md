# datavibes

**A standalone, config-driven toolkit for collecting data and generating datasets.**

`datavibes` is a self-contained Python project — a collection of reusable
scripts (an SDK) plus per-dataset **configuration** — whose single job is:

> pull data from public sources → normalise & derive → emit a ready-made, versioned
> dataset (timestamped CSV snapshots).

It has **no web server, no database, no billing**. It is deliberately *dumb and
deterministic*: given a dataset config and a wall-clock timestamp, it produces the
same dataset every time. Monetisation, API delivery, entitlements and billing live
**elsewhere** — in the VBWD `dataset` plugin, which *consumes* the files this tool
produces (see [Output contract](#output-contract)).

---

## What this is (and is not)

| This project **is** | This project **is not** |
|---|---|
| A CLI you run (locally or from a GitHub Actions cron) | A running service / API |
| An importable Python library (`import datavibes`) | A database or storage backend |
| An SDK of reusable collection + processing code | A payment / entitlement / billing layer |
| A place where each dataset = declarative config + a tiny optional adapter | A scraper zoo with bespoke code per dataset |

**Two ways to use it — one codebase:**

1. **As a CLI** (primary) — the automation surface. GitHub Actions runs
   `datavibes run <slug>` on a schedule; the snapshot is committed/uploaded.
2. **As a dependency** — another Python app can `import datavibes`, register a
   custom source, and drive the same pipeline in-process.

---

## Mental model

```
        ┌─────────────┐     ┌───────────┐     ┌────────────┐     ┌──────────┐
config →│  SOURCES    │ →   │ GENERATOR │  →  │ PROCESSOR  │  →  │ EXPORTER │→ dataset
 (yaml) │ (fetchers)  │ raw │ (snapshot)│ raw │ (normalise │     │  (csv/…) │  snapshot
        └─────────────┘     └───────────┘     │  + derive) │     └──────────┘
                                              └────────────┘
```

Everything a dataset needs is **declared**, not coded:

- **metadata** — slug, title, category, license, update frequency, source attribution
- **schema** — the typed fields (columns) of the output
- **sources** — where the raw records come from (built-in HTTP/JSON/CSV adapters, or a
  small custom `Source` subclass)
- **processing** — the ordered steps (normalise types → dedupe → derive → aggregate →
  validate against schema)

Adding a new dataset is meant to be *minutes, not hours*: `datavibes new <slug>`
scaffolds the config, you fill in the source URL and fields, and `run` it.

---

## Quick start

```bash
# install (editable)
pip install -e .

# scaffold a new dataset
datavibes new hosting-benchmarks --category infrastructure

# validate the config + schema
datavibes validate hosting-benchmarks

# collect a raw snapshot only
datavibes generate hosting-benchmarks

# raw → processed → export (the cron target)
datavibes run hosting-benchmarks

# list all known datasets
datavibes list
```

### As a library

```python
from datavibes import DatasetSDK

sdk = DatasetSDK(root="datasets")
sdk.run("hosting-benchmarks")                       # full pipeline
rows = sdk.dataset("hosting-benchmarks").latest()   # consume in-process
```

Register a bespoke source without touching the SDK:

```python
from datavibes import register_source, Source

@register_source("hetzner-pricing")
class HetznerPricing(Source):
    def fetch(self, ctx):
        ...  # yield dict records
```

---

## Repository layout

```
datavibes/
├── README.md
├── pyproject.toml               # single entrypoint: `datavibes` console script
├── datavibes/            # THE SDK — all reusable code (importable)
│   ├── __init__.py              #   public API: DatasetSDK, Source, Field, register_source
│   ├── cli.py                   #   the ONLY human interface (argparse/click)
│   ├── sdk.py                   #   DatasetSDK facade
│   ├── config/                  #   load + validate DatasetConfig / DatasetMetadata
│   ├── schema/                  #   Field / Schema (typed columns)
│   ├── sources/                 #   Source ABC + registry + built-in adapters
│   ├── generator/               #   Generator (sources → raw snapshot)
│   ├── processing/              #   Processor + pure, testable steps
│   ├── export/                  #   writers (csv / json / parquet)
│   └── store/                   #   on-disk layout + timestamped snapshots
├── datasets/                    # DATA, not code — one folder per dataset
│   └── <slug>/
│       ├── dataset.yaml         #   metadata + schema + sources + processing
│       └── sources.py           #   optional custom Source adapter
├── tests/
└── docs/
    └── dev_log_day/<YYYYMMDD>/  # dev log (sprints / reports / done / walkthrough)
```

The **SDK holds all reusable machinery once**; the `datasets/` tree holds only
declarative config (plus the rare small adapter). This is the whole design goal.

---

## Output contract

`run` writes each snapshot to a path that the VBWD `dataset` plugin already serves:

```
output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv
```

e.g. `environment/air-quality-01a59960/2026-06-01-00-00.csv`. This lets the pipeline be
purely additive: a cron produces the next timestamped snapshot, the delivery layer
picks it up unchanged. **This project never talks to the plugin; it only writes files
in the shape the plugin reads.**

---

## Map datasets (`colored-geostats`)

A dataset can declare several **outputs**. All of them share one timestamp stem. The
`svg-map` writer renders the processed rows as a thermomap (choropleth) next to the CSV:

```yaml
outputs:
  - csv
  - svg-map:
      geometry: natural-earth-admin0-110m   # vendored, sha256-checked (datavibes/maps/geometry/manifest.yaml)
      scope: world                          # world | region (+ region: {iso3: [...]} or {continent: ...}, clip_bbox) | country (admin1 geometry)
      projection: equal-earth               # default for world; equirectangular otherwise
      exclude: [ATA]
      key_column: iso3
      key_aliases: { SSD: SDS }             # data code → geometry code
      label_columns: [density_per_km2]      # tooltip contents
      title: "…"
      footer: "…"
      color_scale: { type: sex-ratio-bivariate, ratio_column: male_share_pct, value_column: density_per_km2 }
```

```
output/world-population-density/<ts>.csv        # the numbers
output/world-population-density/<ts>.svg        # the map
output/world-population-density/<ts>.join.json  # unmatched keys, both directions
```

**Colour scales** (registry: `register_color_scale`):

| `type` | Meaning |
|---|---|
| `sex-ratio-bivariate` | hue = blue (more men) / red (more women) / grey (within `tie_tolerance_pct`); intensity = white blended toward the full hue by density, normalised to `saturation_range` (default 0.1 ≈ white … 1.0 = full colour) |
| `spectral-density` | dark blue (lowest) → sky blue → **green (set average)** → yellow → orange → red (highest); `center: mean \| median`; `saturate_above: <value>` pins red to a threshold (everything ≥ it is red) |

**Dataset parameters.** Both World Population Density datasets declare
`parameters.overpopulated_per_km2` (default **1000**). One YAML anchor feeds the CSV
`overpopulated` flag (via `derive … params:`) and the heat map's `saturate_above`. Try another
value without editing: `OVERPOPULATED_PER_KM2=500 datavibes run world-population-density-heat`.

Both normalise with `normalize: log` (default) or `linear`. They use the same
`scale_to_range` helper as the CSV's `density_saturation` column, so the map and the CSV
always agree. The colour domain is **every row of the dataset**.

**Adding a scale** means one class implementing `ColorScale.paint(rows) -> Painting`,
decorated with `@register_color_scale("name")`. The writer doesn't change.

**Adding a geometry** means vendoring the file and adding a manifest entry with its
sha256. `make geometry` refreshes the Natural Earth file.

Shipped datasets: `world-population-density` (bivariate) and
`world-population-density-heat` (spectral, same CSV).

---

## Configuration — `.env` (secrets) + `config.yaml` (app settings)

Two project-root files configure a run. Both are **optional** — with neither present the
SDK falls back to built-in defaults. They are loaded at SDK/CLI startup, `.env` first,
*before* any `${VAR}` interpolation in `config.yaml` or a `dataset.yaml`.

### `.env` — secrets only
A tiny stdlib parser (no `python-dotenv` dep): `KEY=VALUE`, `#` line comments, blank
lines, optional `export` prefix, quotes stripped. **Real process environment variables
always win** — the loader never overwrites an already-set variable.

- `.env` is **gitignored**; commit **`.env.example`** instead. Copy it to `.env` and fill in.
- Secrets referenced by the shipped datasets: `NCEI_TOKEN`, `OPENWEATHERMAP_API_KEY`.
- Non-secret knobs may also live here: `DATAVIBES_USER_AGENT`, and the optional
  `DATAVIBES_OUTPUT_DIR` (see below).

### `config.yaml` — app-level, non-secret
Committed with documented defaults. String values support `${VAR}` and `${VAR:-default}`
interpolation. **Secrets never go here.**

```yaml
paths:   { datasets_root: datasets, output_root: output, store_root: store }
http:    { timeout_seconds: 30, max_retries: 3, backoff_seconds: 0.5,
           user_agent: "${DATAVIBES_USER_AGENT:-datavibes/0.1 (+https://vbwd.cc)}" }
defaults:{ units: metric, format: csv }
```

`FileStore` takes its roots from `paths`; the HTTP sources take timeout / retries /
User-Agent from `http`; the default export format comes from `defaults.format`.

### Precedence
- **Secrets:** `.env` / process env **only** (real env > `.env`), never `config.yaml`.
- **Output root:** `DATAVIBES_OUTPUT_DIR` (env/`.env`, treated as an absolute path — a
  relative value resolves against the project root) **>** `config.yaml paths.output_root`
  **>** default `output/`.
- **Everything else:** explicit CLI arg / SDK kwarg **>** `config.yaml` **>** built-in default.

### Inspect the effective config
`datavibes config` prints the resolved configuration with **secret values masked**
(`NCEI_TOKEN = ***set***` / `***unset***`) — safe to paste into an ops ticket. Paths
(including `DATAVIBES_OUTPUT_DIR`) are shown in full; they are not secrets.

---

## Design principles

- **Config over code** — a new dataset is config; bespoke code is the exception.
- **Deterministic & idempotent** — same config + same timestamp → same bytes.
- **Pure processing steps** — every transform is a testable function, no I/O.
- **Open/closed via a source registry** — add adapters without editing the SDK.
- **CLI-only + importable** — no server, no hidden global state.
- **Public sources only** — no manual data entry, no per-customer scraping.

See [`docs/dev_log_day/20260704/sprints/s01-dataset-generator.md`](docs/dev_log_day/20260704/sprints/s01-dataset-generator.md)
for the full scaffolding architecture.

## Catalog coverage — any dataset is just config

datavibes ships a **finite, shared library of built-in primitives** so that a whole
catalog of datasets is authorable as config, not code:

- **Source adapters** — `static`, `http_json`, `http_csv`, `paged_http_json` (page /
  offset / cursor paging + an env-var bearer token), `multi_http_json` (fan out over a
  declared item list, one request each), `columnar_http_json` (transpose an API's
  parallel arrays into rows), `jsonstat` (Eurostat / e-Stat cubes) and
  `worldbank-indicator`. A per-dataset `sources.py` is the exception (~30 lines), only
  when a source's auth/paging/shape is unique.
- **Processing steps** — `normalize`, `rename`, `dedupe`, `filter`, `sort`, `join`,
  `derive`, `aggregate`, `age_days`, `score`, `flag`, `classify`, `forecast`, `validate`.
- **Derive helpers** — `yoy`, `pct_change`, `cagr`, `rolling_avg`, `anomaly`, `corr` /
  `rolling_corr`, `ratio`, `add`, `subtract`, `share` / `penetration`, `share_of_total`,
  `gini`, `hhi`, `minmax_normalize`, `zscore`, `volatility`, `seasonal_index`,
  `linear_forecast`.

Every "statistical preprocessing" requirement in the product catalog (aggregates,
anomalies, rolling averages, correlations, growth rates, inequality metrics, geographic
joins, scoring, forecasting, concentration, volatility, …) maps onto one of these named
primitives. A row-by-row proof that all **30** catalog datasets are covered is in
[`docs/dev_log_day/20260704/reports/r01-dataset-catalog-coverage.md`](docs/dev_log_day/20260704/reports/r01-dataset-catalog-coverage.md);
the primitives that report called for were completed in
[`docs/dev_log_day/20260811/sprints/s12-catalog-primitives-and-datasets.md`](docs/dev_log_day/20260811/sprints/s12-catalog-primitives-and-datasets.md).

> **Not built:** an `sdmx` adapter. Every SDMX source the catalog needs (Eurostat,
> World Bank) is reachable through `jsonstat` or `worldbank-indicator`, and the one
> SDMX-JSON endpoint worth adding it for (the ECB Data Portal) blocks non-browser
> clients — so there is nothing to test it against yet.
