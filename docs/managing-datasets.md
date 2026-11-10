# Managing datasets

This guide is for **operating** the datasets that already exist: running them,
configuring them, scheduling them, reading their output and fixing them when a
run goes wrong. To build a new one, see [creating-datasets.md](creating-datasets.md).
Every option is listed in [reference.md](reference.md).

---

## 1. Setup

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'          # add ,report / ,parquet / ,openai extras as needed
cp .env.example .env                        # secrets (optional; see §3)
cp config.yaml.dist config.yaml             # app settings (optional; see §3)
.venv/bin/pytest -q                         # whole suite, network fully mocked
```

> **Check which copy you are running.** `pip install -e .` binds the `datavibes`
> command to *one* checkout. If you keep several clones, confirm with
> `python -c "import datavibes; print(datavibes.__file__)"`.

Optional extras (`pyproject.toml`):

| Extra | Enables |
|---|---|
| `dev` | `pytest` |
| `parquet` | `--format parquet` (pyarrow) |
| `report` | LLM report PDF + charts (anthropic, fpdf2, matplotlib, markdown) |
| `openai` | OpenAI-compatible LLM providers (DeepSeek, …) for reports |
| `report-html` | Full-fidelity HTML/CSS report template (weasyprint; needs system pango/cairo) |

---

## 2. The command line

Every command is also available from Python through `DatasetSDK` (§7).

| Command | What it does |
|---|---|
| `datavibes list` | All datasets under `datasets/`: slug, category, title |
| `datavibes info <slug>` | Latest snapshot path + row count |
| `datavibes validate <slug>` | Parses `dataset.yaml`, then resolves every source, step and output writer. **Run it after every edit.** |
| `datavibes generate <slug>` | Fetches sources → raw snapshot `store/raw/<slug>/<ts>.jsonl` (no processing) |
| `datavibes process <slug>` | Latest raw snapshot → processed rows (prints the count) |
| `datavibes export <slug> [--format csv\|json\|parquet]` | Re-exports the latest raw snapshot **without refetching** |
| `datavibes run <slug>` | **The cron target:** generate → process → write every declared output |
| `datavibes report <slug>` | LLM-authored `analytics.md` + `statistics.md` + `report.pdf` (see [charts.md](charts.md)) |
| `datavibes config` | Prints the effective configuration (secrets masked) |
| `datavibes new <slug> --category <c>` | Scaffolds a dataset that already passes `validate` |
| `datavibes --root <dir> …` | Uses another datasets folder |

A typical maintenance loop:

```bash
datavibes validate world-population-density
datavibes run world-population-density
datavibes info world-population-density
```

`generate` and `process` are separate on purpose. When an API is slow or
rate-limited, fetch once with `generate`, then iterate on `processing:` with
`process` / `export` as often as you like, without calling the API again.

---

## 3. Configuration

Three layers, each optional:

| File | Holds | Committed? |
|---|---|---|
| `.env` | **Secrets only** (API tokens). Loaded first; real environment variables win. | No (`.env.example` is) |
| `config.yaml` | App settings: paths, HTTP, defaults, LLM reports | No; copy from `config.yaml.dist` |
| `datasets/<slug>/dataset.yaml` | Everything about one dataset | Yes |

> `config.yaml.dist` is a **template that no code reads**. Without a
> `config.yaml`, built-in defaults apply. **Careful:** the template sets
> `llm.enabled: true` (the built-in default is `false`), so copying it unchanged
> turns on LLM report generation, which means paid API calls, on every `run`.

### `config.yaml` keys

| Key | Default | Meaning |
|---|---|---|
| `paths.datasets_root` | `datasets` | Where dataset folders live |
| `paths.output_root` | `output` | Where snapshots land (overridden by `$DATAVIBES_OUTPUT_DIR`) |
| `paths.store_root` | `store` | Raw snapshots |
| `paths.output_layout` | `slug` | `slug` → `output/<slug>/` · `category` → `output/<category>/<slug>-<hash>/` (legacy VBWD plugin contract) |
| `http.timeout_seconds` | `30` | Per request (the `sparql` source uses its own, 90 s) |
| `http.max_retries` / `backoff_seconds` | `3` / `0.5` | 5xx/429 retries, linear backoff |
| `http.user_agent` | `datavibes/0.1` | Some APIs (Wikidata, NOAA) require a descriptive one |
| `defaults.format` | `csv` | Output for datasets that declare no `outputs:` |
| `llm.*`, `report.*` | `enabled: false` | See `config.yaml.dist` and [charts.md](charts.md) |

**Precedence:** CLI argument / SDK keyword > environment > `config.yaml` > built-in
default. Secrets come **only** from `.env` or the environment, and `datavibes config`
masks them.

### Secrets used by the shipped datasets

| Variable | Needed by | Without it |
|---|---|---|
| `NCDC_WEB_SERVICE_TOKEN` | `us-regional-weather` | The source fails → empty snapshot (warning printed) |
| `GITHUB_TOKEN` | `oss-project-health`, `programming-language-adoption` | Works, but GitHub's anonymous rate limit (60/h) may drop rows |
| `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` | Reports only | `report` fails; `run` keeps working |

---

## 4. Dataset parameters (tuning without editing)

Datasets expose their tunable values as `${VAR:-default}` placeholders,
usually gathered in a `parameters:` block at the top of `dataset.yaml`.
Override them per run:

```bash
OVERPOPULATED_PER_KM2=500 datavibes run world-population-density-heat
CITY_MIN_POPULATION=500000 CITY_OVERPOPULATED_PER_KM2=5000 datavibes run world-city-population-density
```

| Variable | Dataset(s) | Default | Effect |
|---|---|---|---|
| `OVERPOPULATED_PER_KM2` | `world-population-density`, `-heat` | 1000 | CSV `overpopulated` flag; red end of the heat map |
| `CITY_MIN_POPULATION` | `world-city-population-density`, `-heat` | 100000 | Smallest city fetched (inside the SPARQL query) |
| `CITY_OVERPOPULATED_PER_KM2` | same | 10000 | City `overpopulated` flag; red end of the city heat map |
| `EGG_WEIGHT_GRAMS` | `egg-purchasing-power` | 60 | Grams per egg: FAO prices are per tonne |

To change a default permanently, edit the value after `:-` in `dataset.yaml`.

The city heat maps (world and the nine regions) draw **population density between the
cities** from the vendored GHSL 2025 grid (`datavibes/maps/rasters/`, about 1 MB):
grey below 10 people/km², blue → red up to 2,000, red above. To refresh the grid from the
JRC (a 484 MB download, needs `numpy`, `tifffile`, `imagecodecs`): `make population-grid`.

The nine `cities-heat-rN-*` regional maps are **generated**: edit the region table in
`scripts/make_region_city_maps.py` and run `python scripts/make_region_city_maps.py`
(`--check` fails if a generated file is stale; a test runs it too). Do not edit their
`dataset.yaml` files by hand.

---

## 5. Output

```
output/<slug>/                       # paths.output_layout: slug (default)
├── 2026-11-06-16-14.csv             # the data (one file per run; UTC timestamp)
├── 2026-11-06-16-14.svg             # map datasets: the map
├── 2026-11-06-16-14.join.json       # map datasets: what matched, what was excluded and why
├── analytics.md, statistics.md      # only with LLM reports
└── report.pdf, charts/
store/raw/<slug>/<ts>.jsonl          # immutable raw snapshot of every run
```

- **Snapshots are append-only.** Each run adds a new timestamp. `info` and the
  library's `latest_rows()` always read the newest CSV. Prune old files yourself.
- **Byte-stable:** the same raw data and the same timestamp give identical files.
  This makes snapshots diffable and safe to commit.
- **Map datasets** write a CSV, an SVG and a `join.json` with one shared
  timestamp. The map legend ends with a **Coverage** block ("Cities shown: 3,236
  of 4,017 · Not included: 781 — …"), and `join.json` holds the same counts.

---

## 6. Scheduling

`run` is idempotent and safe to cron. Match the cadence to each dataset's
`metadata.update_frequency`, which describes how often the *source* publishes:

```cron
# m h dom mon dow  command
15 3 * * *   cd /srv/datavibes && .venv/bin/datavibes run oss-project-health
30 3 1 * *   cd /srv/datavibes && .venv/bin/datavibes run world-population-density
```

The `Makefile` also has a container workflow (`make run DATASET=<slug>`) that
stages the tree into the VBWD backend container. `make test` runs the suite, and
`make geometry` re-vendors the Natural Earth map geometry.

---

## 7. Using the data from Python

```python
from datavibes import DatasetSDK

sdk = DatasetSDK()                                   # reads .env + config.yaml
paths = sdk.run_outputs("world-population-density")  # [csv, svg] of this run
rows = sdk.latest_rows("world-population-density")   # list[dict] from the newest CSV
print(sdk.info("world-population-density"))
```

`DatasetSDK(clock=FixedClock(...), store=FileStore(tmp), http_factory=...)`
injects every collaborator. That is how the tests run the pipeline offline and
deterministically.

---

## 8. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `warning: source failed -> <type>#<n>: …` and a tiny or empty CSV | By design a failed source contributes **zero rows** instead of crashing the run. Read the message: a missing token (§3), a rate limit (retry later, add a token), or a timeout. |
| `Read timed out (read timeout=30.0)` | A slow API. Raise `http.timeout_seconds`; SPARQL has its own `timeout_seconds` option. Wikidata caps queries at 60 s server-side, so a query that needs more must be restructured, not just given longer. |
| `validate` → `unknown source type 'x' (known: …)` | A typo, or a dataset-local `sources.py` that failed to import |
| `validate` → `keywords must be strings` | A bare YAML key `on:` (also `yes`, `no`, `off`) parses as a boolean. Quote it: `"on": iso3`. |
| `SchemaValidationError: row 3 missing column(s): …` | A source didn't emit a column. Mark it `nullable: true`, or derive it before `validate`. |
| A map has many grey countries | Look in `<ts>.join.json`: `features_without_rows` means the data has no row for that shape. `rows_not_drawn` means a code mismatch (add `key_aliases`) or a micro-state too small for the 110m geometry. |
| `geometry file … failed its checksum` | The vendored GeoJSON was edited. Run `make geometry` and update the sha256 in `datavibes/maps/geometry/manifest.yaml`. |
| `test_cli_new_validate_run_flow` fails locally only | Your `.env` sets `DATAVIBES_OUTPUT_DIR` to a container path. Run the tests with it unset or overridden. |

---

## 9. Dataset catalog

Generated from each `dataset.yaml`. "Env" lists secrets and tunable parameters.

| Slug | Category | Cadence | Sources | Outputs | Env | Report charts |
|---|---|---|---|---|---|---|
| `ai-model-performance` | infrastructure | daily | paged_http_json | csv | — | yes |
| `air-quality-pollution` | environment | hourly | columnar_http_json | csv | — | yes |
| `carbon-emissions-trajectory` | environment | annual | http_csv, worldbank-indicator | csv | — | yes |
| `egg-purchasing-power` | economy | annual | worldbank-indicator, worldbank-pinksheet, bls-series, jsonstat, ilostat, bis-series, static, faostat-prices | csv, xlsx, 7 × svg-small-multiples | `EGG_WEIGHT_GRAMS` | yes |
| `energy-renewable-share` | energy | annual | worldbank-indicator | csv | — | yes |
| `eu-economic-demographic` | macro | annual | jsonstat | csv | — | yes |
| `eu-tech-job-market` | infrastructure | annual | jsonstat | csv | — | yes |
| `hosting-cloud-pricing` | infrastructure | daily | cloud-price-list (local `sources.py`) | csv | — | yes |
| `oss-project-health` | infrastructure | daily | multi_http_json | csv | `GITHUB_TOKEN` | yes |
| `power-price-volatility` | energy | daily | columnar_http_json | csv | — | yes |
| `programming-language-adoption` | infrastructure | weekly | multi_http_json | csv | `GITHUB_TOKEN` | yes |
| `renewable-grid-status` | energy | daily | columnar_http_json | csv | — | yes |
| `tech-salary-compensation` | infrastructure | annual | jsonstat | csv | — | yes |
| `us-regional-weather` | environment | daily | ncei-climate (local `sources.py`) | csv | `NCDC_WEB_SERVICE_TOKEN` | yes |
| `vehicle-production-ev-share` | mobility | annual | iea-ev (local `sources.py`) | csv | — | yes |
| `world-bank-global-development` | macro | annual | worldbank-indicator | csv | — | yes |
| `cities-heat-r1-north-america` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: USA, Canada, Mexico) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r2-europe` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: Portugal to the Urals) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r3-middle-east` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: Turkey, Levant, Egypt, Iraq, Iran, Arabia) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r4-south-asia` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: Afghanistan to Bangladesh) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r5-southeast-asia` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: Myanmar to the Philippines) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r6-east-asia` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: China, Koreas, Japan, Taiwan) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r7-former-ussr` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: ex-USSR without the Baltics, + Mongolia) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r8-africa` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: Africa) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `cities-heat-r9-latin-america` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map (region: Mexico to Argentina) | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `world-city-population-density` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map | `CITY_MIN_POPULATION`, `CITY_OVERPOPULATED_PER_KM2` | — |
| `world-city-population-density-heat` | colored-geostats | monthly | sparql, worldbank-latest | csv, svg-dot-map | same | — |
| `world-population-density` | colored-geostats | monthly | worldbank-latest | csv, svg-map | `OVERPOPULATED_PER_KM2` | — |
| `world-population-density-heat` | colored-geostats | monthly | worldbank-latest | csv, svg-map | same | — |

### Retiring or renaming a dataset

- **Retire:** delete `datasets/<slug>/` and remove its cron line. Old snapshots in
  `output/<slug>/` stay until you delete them.
- **Rename the slug:** the output folder changes, and under the `category` layout
  so does the `<slug>-<hash>` suffix. Consumers of the old path must be updated.
  Treat it as a new dataset.
- **Change the schema:** adding a column is safe. Renaming or removing one breaks
  consumers of the CSV, so publish it as a new slug, or announce the change.
