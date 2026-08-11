# S12 — Close the catalog primitive gap, then ship the next dataset batch

**Date:** 2026-08-11 · **Status:** done
**Basis:** [`../../20260704/reports/r01-dataset-catalog-coverage.md`](../../20260704/reports/r01-dataset-catalog-coverage.md)
(the row-by-row proof that all 30 catalog datasets decompose into a *finite* primitive
library) · [`_engineering_requirements.md`](_engineering_requirements.md)

## Goal

R01 promised that once a closed set of adapters/steps/helpers existed, datasets 1–30
would be **config only**. Part of that set was still unbuilt. This sprint builds the
remainder and then proves it by authoring — and *running live* — the next batch of
sellable datasets straight off the product priority list.

## Part A — the primitive gap (TDD, network mocked)

### Source adapters
| Adapter | Why it exists | Consumers |
|---|---|---|
| `paged_http_json` | page / offset / cursor paging + optional env-var bearer token; `fields` maps dotted paths onto schema columns | AI model performance (HF `skip`/`limit`) |
| `multi_http_json` | "N entities, one endpoint each" — renders `{key}` from each item into URL *and* params; a failing item costs one row, not the snapshot | OSS health (GitHub/npm/PyPI), language adoption (GitHub search, Stack Overflow) |
| `columnar_http_json` | transposes an API's parallel arrays (`time[]` + `pm10[]`) back into rows; tolerates a short value array | air quality (Open-Meteo), grid status + power prices (energy-charts) |
| `jsonstat` | decodes a dense JSON-stat 2.0 cube — reverses the row-major flattening, emits codes and/or labels per dimension | EU jobs, EU macro, tech salary |
| `worldbank-indicator` | **promoted** from `datasets/energy-renewable-share/sources.py` into the SDK once a third dataset needed it | energy mix, WB development, carbon trajectory |

### Processing steps
`flag` (threshold/membership/null predicates under `when`/`all`/`any`) · `classify`
(ordered numeric bins → label) · `forecast` (trailing least-squares fit projected
`horizon` periods ahead, per group) · `filter` (same predicates as `flag`, but drops
rows) · `rename` (publisher CSV headers → schema columns, *before* `normalize`) ·
`age_days` (staleness in days against the **injected** clock).

### Derive helpers
`gini` · `hhi` · `zscore` · `seasonal_index` · `share_of_total` · `add` · `subtract` ·
`linear_forecast`.

### Incidental hardening
- `request_with_retry` now treats **429** as transient. Every polite public API in this
  batch (energy-charts, GitHub, World Bank) meters callers and expects a backed-off retry.
- `config.yaml` default retry budget raised to 5 attempts / 2 s linear backoff.
- `worldbank-indicator` paces its indicator + page loop (`delay_seconds`, default 1.0).
  Without it a six-indicator burst returns an **empty** snapshot, not an error — the
  generator degrades a failed source to zero rows by design, so the symptom was a
  silently empty CSV.
- `DeriveStep._groups` and the new `ForecastStep` share one `_group_indices` helper.

## Part B — datasets authored and run live

Priority order taken from the product catalog scoring. Every one is **config only** —
no new `sources.py` was written in this sprint.

| # | Slug | Catalog row | Sources |
|---|---|---|---|
| 24 | `ai-model-performance` | AI Model Performance (4.45) | Hugging Face Hub |
| 12 | `oss-project-health` | OSS Project Health & Risk (4.45) | GitHub + npm + PyPI |
| 11 | `eu-tech-job-market` | EU Tech Job Market (4.20) | Eurostat `jvs_a_rate_r2`, `isoc_sks_itspt` |
| 20 | `tech-salary-compensation` | Tech Salary & Compensation (4.20) | Eurostat `lc_lci_lev`, `tec00114` |
| 28 | `programming-language-adoption` | Programming Language Adoption (4.10) | GitHub Search + Stack Exchange |
| 4 | `eu-economic-demographic` | EU Economic & Demographic (3.90) | Eurostat `tps00001`, `tec00114`, `tec00118`, `une_rt_a` |
| 3 | `air-quality-pollution` | Air Quality & Pollution (3.75) | Open-Meteo Air Quality (CAMS) |
| 26 | `renewable-grid-status` | Renewable Grid Status (3.60) | energy-charts daily-average shares |
| 17 | `carbon-emissions-trajectory` | Carbon Pricing & Emissions (3.35) | OWID Global Carbon Budget + World Bank |
| 5 | `world-bank-global-development` | World Bank Global Development (3.30) | World Bank Indicators |
| 22 | `power-price-volatility` | Commodity Price Volatility (3.10) | energy-charts day-ahead spot |

## Deliberately not built (and why)

- **#23 Global Hosting Performance** — no keyless benchmark feed exists. Geekbench and
  the CDN/latency vendors are licence- or key-gated; a "cost per unit of performance"
  bundle with #10 needs a purchased or self-generated benchmark corpus first.
- **#2 US Census Demographics** — `api.census.gov` now rejects keyless calls
  (`Missing Key`). Unblocked the moment a `CENSUS_API_KEY` lands in `.env`;
  `paged_http_json` already carries the token plumbing.
- **#16 EU TED / #30 municipal procurement / #13 EU regulatory** — the `hhi` and
  `classify` primitives they need now exist, but every source is a POST-search or a
  gazette scrape. Highest price point in the catalog and the most fragile source: worth
  a sprint of its own, not a corner of this one.
- **#22 as a *metals/ags* commodity feed** — Stooq is JS-gated, Yahoo's chart endpoint
  rate-limits anonymous callers, and the World Bank Pink Sheet is an Excel workbook.
  Shipped instead as **European day-ahead power**, a real commodity market with a
  keyless CC-BY-4.0 feed at quarter-hourly resolution.
- **`sdmx` adapter** — nothing left to point it at. See the README note.

## Acceptance

- `.venv/bin/pytest -q` green (**219** tests, **52** of them new in `tests/test_s12_primitives.py`).
- Every dataset above passes `datavibes validate` and has produced a real
  `output/<slug>/<timestamp>.csv` from a live fetch — counted in
  [`../reports/r04-s12-dataset-batch-results.md`](../reports/r04-s12-dataset-batch-results.md).
