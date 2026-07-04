# S06 — First dataset generator: US Regional Weather & Climate Trends

**Date:** 2026-07-04 · **Type:** Sprint plan + developer walkthrough · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md).
**Depends on:** the full SDK — S02 (core), S03 (generator/sources), S04 (processor/steps),
S05 (exporter/writers). This sprint writes **no SDK code**; it authors the first *dataset*
purely as config + one small source adapter, proving the "config, not code" promise.

**Trigger.** Ship the first production dataset from the 2026-07-04 product brief and use it
as the copyable template for every dataset after it.

---

## Dataset brief

| Field | Value |
|---|---|
| **Topic** | US Regional Weather & Climate Trends |
| **Data sources (free APIs)** | NOAA / NCEI (Climate Data Online), OpenWeatherMap |
| **Statistical preprocessing** | Aggregates, anomalies, rolling averages, correlations |
| **Value proposition** | Local climate-intelligence reports + maps |
| **Target buyers** | Agriculture, insurance, retail, logistics |
| **Update regularity** | Daily |
| **Size per update** | 2–8 MB |

---

## What the developer actually does (the whole point)

Because S02–S05 built the machinery, a new dataset is **one folder**:

```
datasets/us-regional-weather/
├── dataset.yaml     # metadata + schema + sources + processing (declarative)
└── sources.py       # ONE small adapter for NOAA/NCEI (token auth + station paging)
```

Then: `datavibes validate us-regional-weather && datavibes run us-regional-weather`.
That is the entire developer experience this project exists to deliver.

### Step 1 — scaffold
```bash
datavibes new us-regional-weather --category environment
```
Produces a `static`-source `dataset.yaml` that already passes `validate` (green before any
real API is wired).

### Step 2 — declare metadata + schema (`dataset.yaml`)
```yaml
metadata:
  slug: us-regional-weather
  title: US Regional Weather & Climate Trends
  category: environment
  license: "NOAA public domain / OpenWeatherMap CC-BY-SA"
  update_frequency: daily
  attribution: "NOAA NCEI Climate Data Online; OpenWeatherMap"

schema:
  - { name: region,              dtype: str }
  - { name: date,                dtype: date }
  - { name: temp_mean_c,         dtype: float, unit: "°C" }
  - { name: temp_anomaly_c,      dtype: float, unit: "°C",  description: "vs 30y baseline" }
  - { name: precip_mm,           dtype: float, unit: "mm" }
  - { name: temp_roll7_c,        dtype: float, unit: "°C",  description: "7-day rolling mean" }
  - { name: precip_temp_corr,    dtype: float, description: "rolling precip–temp correlation" }
```

### Step 3 — declare sources
```yaml
sources:
  - type: ncei-climate            # custom adapter in sources.py (token + station paging)
    dataset: GHCND
    stations_file: stations.us.txt
    metrics: [TMAX, TMIN, PRCP]
    lookback_days: 400            # enough history for rolling + baseline
  - type: http_json               # built-in — current conditions to freshen "today"
    url: https://api.openweathermap.org/data/2.5/weather
    select: "$"
    params: { appid: "${OPENWEATHERMAP_API_KEY}" }
```
- `ncei-climate` is the **only bespoke code** — ~30 lines subclassing `Source`,
  registered with `@register_source("ncei-climate")`, handling the NCEI token header and
  station pagination. Everything else is a built-in.
- Secrets (`NCEI_TOKEN`, `OPENWEATHERMAP_API_KEY`) come from env — never committed.

### Step 4 — declare the statistical preprocessing (maps straight onto S04 steps)
```yaml
processing:
  - normalize                                              # coerce to schema dtypes/units
  - dedupe:    { keys: [region, date] }
  - aggregate: { by: [region, date], metrics: { temp_mean_c: mean, precip_mm: sum } }
  - derive:    { column: temp_anomaly_c,   expr: anomaly(temp_mean_c, baseline=climatology) }
  - derive:    { column: temp_roll7_c,     expr: rolling_avg(temp_mean_c, window=7) }
  - derive:    { column: precip_temp_corr, expr: rolling_corr(precip_mm, temp_mean_c, window=30) }
  - validate                                               # fail loud if schema breached
```
- **Aggregates** → `aggregate`; **anomalies** → `anomaly(...)`; **rolling averages** →
  `rolling_avg(...)`; **correlations** → `rolling_corr(...)`. Three of four are existing
  S04 helpers; **`rolling_corr` is the one new pure helper** this sprint adds to
  `processing/functions.py` (with its own unit test).

### Step 5 — run + verify size/cadence
```bash
datavibes run us-regional-weather
# → output/environment/us-regional-weather-<hash>/2026-07-04-06-00.csv  (~2–8 MB)
```
A daily GitHub Actions cron runs exactly this line; the snapshot is committed/uploaded and
the `dataset` plugin serves it unchanged ([[project_s110_datasets_plugin]]).

---

## What this sprint adds to the SDK (kept minimal — no overengineering)

1. `datasets/us-regional-weather/sources.py` — the `ncei-climate` adapter (bespoke,
   because NCEI needs token + station paging no generic adapter covers).
2. `rolling_corr(col_a, col_b, window)` pure helper in `datavibes/processing/functions.py`
   (the only genuinely new reusable primitive; everything else already exists).

Nothing else in `datavibes/` is touched — the promise of S01 (SDK once, datasets as config)
is the acceptance criterion.

---

## Tests

- **`ncei-climate` adapter** (network mocked): token header sent; station pagination
  walks all pages; a recorded NCEI GHCND body maps to `region/date/metric` rows; empty
  station → empty, not crash.
- **`rolling_corr` helper** (pure): known series → known correlation; short series (< window)
  → null/NaN handled; zero-variance window guarded.
- **End-to-end fixture run**: a `static` stand-in for both sources (recorded NCEI +
  OpenWeatherMap bodies) → `datavibes run` produces a golden CSV at the contract path,
  byte-stable under `FixedClock`, columns exactly the declared schema.
- **Size sanity**: the fixture-scaled run asserts row-count/size land in the expected band
  (documents the 2–8 MB/day envelope without hitting live APIs).

---

## Scope
**IN:** the `us-regional-weather` dataset folder (config + `ncei-climate` adapter),
`rolling_corr` helper, and the tests above.
**OUT:** live-API integration in CI (mocked only), the GitHub Actions cron workflow
(follow-up), and any second dataset (S07+, same template).

## Definition of done
- [ ] `datavibes validate us-regional-weather` passes; `datavibes run us-regional-weather`
      writes `output/environment/us-regional-weather-<hash>/<ts>.csv`.
- [ ] Only **two** SDK-side additions exist (the one adapter + `rolling_corr`); nothing else
      in `datavibes/` changed — the config-not-code promise holds.
- [ ] Adapter, helper, and end-to-end fixture tests green with **zero** live network.
- [ ] Golden CSV is byte-stable under a fixed clock and carries exactly the schema columns.
