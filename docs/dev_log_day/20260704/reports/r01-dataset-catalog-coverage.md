# R01 — 30-dataset catalog coverage on datavibes

**Date:** 2026-07-04 · **Type:** Design analysis · **Status:** reference
**Basis:** [`../sprints/s01-dataset-generator.md`](../sprints/s01-dataset-generator.md)
(architecture) + S02–S05 (SDK layers).

**Question.** *Can every dataset in the 30-row product catalog be rendered by datavibes
as pure config + (rarely) a small adapter — i.e. without changing the SDK per dataset?*

**Answer.** Yes. All 30 decompose into the same three primitive kinds the SDK already
models — **source adapters**, **processing steps/helpers**, and a **schema**. The catalog
does, however, require a *fixed, finite* library of built-in primitives larger than the
S03/S04 starter set. This report enumerates that library and proves coverage row-by-row.
The primitive library is closed: once built (S02–S05 + the S07 gap sprint below), datasets
1–30 are all config.

---

## Primitive library the catalog demands

### Source adapters (`@register_source`)
| Adapter | Covers | Status |
|---|---|---|
| `http_json` | any JSON REST endpoint w/ JSONPath select | S03 ✓ |
| `http_csv` | bulk CSV / TSV downloads | S03 ✓ |
| `paged_http_json` | token/api-key + cursor/page paging (generic) | **S07 new** |
| `jsonstat` | JSON-stat decoder (Eurostat, e-Stat) → tidy rows | **S07 new** |
| `sdmx` | SDMX decoder (Eurostat/World Bank SDMX) | **S07 new** |
| bespoke `<slug>` adapter | only when auth/paging/shape is unique (e.g. `ncei-climate`) | per-dataset |

> Design note: `paged_http_json` + `jsonstat` + `sdmx` collapse ~20 of the 30 sources into
> config-only. A per-dataset `sources.py` is the exception, not the rule — and when needed
> it's ~30 lines subclassing `Source`.

### Processing steps (`@register_step`)
| Step | Purpose | Status |
|---|---|---|
| `normalize` | coerce to schema dtypes/units | S04 ✓ |
| `dedupe` | drop dup rows by keys | S04 ✓ |
| `derive` | add computed column via a pure helper | S04 ✓ |
| `aggregate` | group + reduce (mean/median/sum/min/max/count) | S04 ✓ |
| `validate` | assert schema conformance, fail loud | S04 ✓ |
| `join` | join rows across sources / geographies on keys | **S07 new** |
| `score` | weighted composite score from columns | **S07 new** |
| `flag` | boolean/threshold flags (e.g. greenwashing, stress) | **S07 new** |
| `classify` | rule-based bucketing (impact class, tiers, timelines) | **S07 new** |
| `forecast` | short-horizon projection (linear / Holt) | **S07 new** |

### Pure derive helpers (`processing/functions.py`, each unit-tested)
| Helper | Purpose | Status |
|---|---|---|
| `yoy`, `pct_change` | year-over-year / period change | S04 ✓ |
| `rolling_avg` | rolling mean | S04 ✓ |
| `anomaly` | deviation vs. baseline/climatology | S04 ✓ |
| `rolling_corr`, `corr` | rolling / static correlation | S04+S06 ✓ / **S07 corr** |
| `cagr` | compound growth trajectory | **S07 new** |
| `gini` | inequality metric | **S07 new** |
| `hhi` | concentration (supplier/market) | **S07 new** |
| `minmax_normalize`, `zscore` | price/perf normalization, standardization | **S07 new** |
| `share`, `penetration` | ratio of part to whole (renewable %, EV %) | **S07 new** |
| `volatility` (rolling std) | price/emission volatility | **S07 new** |
| `seasonal_index` | seasonal-pattern extraction | **S07 new** |

That is the **entire** additional surface the catalog needs. It is finite and shared —
exactly the DRY/OCP payoff the SDK exists for.

---

## Coverage matrix (all 30)

Legend — S = source adapter(s), P = processing steps/helpers beyond `normalize`+`validate`
(always implied). "bespoke" = a small per-dataset `sources.py`.

| # | Topic | S | P |
|---|---|---|---|
| 1 | US Regional Weather & Climate | `ncei-climate` (bespoke), `http_json` (OWM) | aggregate, `anomaly`, `rolling_avg`, `rolling_corr` |
| 2 | US Census Demographics & Economy | `paged_http_json` (ACS) | `join` (geo), `cagr`/growth, `gini`, aggregate |
| 3 | Air Quality & Pollution | `http_json` (AirNow), `http_json`/`sdmx` (World Bank) | aggregate (AQI), `seasonal_index`, `score` (health risk) |
| 4 | EU Economic & Demographic | `jsonstat` (Eurostat) | `join` (cross-country), 5y trend via `aggregate`+`cagr` |
| 5 | World Bank Global Development | `sdmx`/`http_json` (WB) | `cagr`, `corr`, aggregate (region focus) |
| 6 | Japan Demographics & Economy | `jsonstat` (e-Stat, `paged_http_json`) | aggregate (aging), `join` (regional), `cagr` |
| 7 | Ag Commodities → Processed Food | `http_json`/`http_csv` (FAOSTAT), `paged_http_json` (Comtrade) | `join`, `share` (processing ratio), `corr` (price) |
| 8 | Energy → Renewable Share | `http_csv` (IEA/IRENA), `sdmx` (WB) | `share`/`penetration`, `cagr`, `score` (transition idx) |
| 9 | Vehicle Production → EV Share | `http_csv` (OICA), `http_json` (IEA EV) | `penetration`, `corr` (infra), `cagr` |
| 10 | Hosting & Cloud Pricing | `http_json` per provider (bespoke where needed) | `minmax_normalize` (price/perf), `volatility` |
| 11 | EU Tech Job Market | `jsonstat` (Eurostat), `paged_http_json`/`http_json` (boards) | aggregate (skill demand), synthesis via `aggregate`+`derive`, velocity `pct_change` |
| 12 | OSS Project Health & Risk | `paged_http_json` (GitHub), `http_json` (NPM/PyPI) | `score` (maintenance), aggregate (community), `flag` |
| 13 | EU Regulatory Compliance | `http_json`/bespoke (EU OJ) | `classify` (impact), timeline via `derive` |
| 14 | Global Startup Hiring | `paged_http_json`/`http_json` (jobs, filings) | aggregate (team growth), `flag` (skill gaps) |
| 15 | Corporate ESG Performance | `http_csv`/bespoke (filings, CDP) | `score`, `flag` (greenwashing) |
| 16 | Government Procurement (EU TED) | `paged_http_json`/`http_csv` (TED) | `hhi` (supplier concentration), `aggregate` (price trends) |
| 17 | Carbon Pricing & Emissions | `http_csv`/bespoke (EU ETS) | `forecast` (emissions), cost model via `derive` |
| 18 | Patent & Innovation | `paged_http_json` (USPTO/EPO/WIPO) | aggregate (filing trends), `cagr` (tech emergence) |
| 19 | City & Regional Development | `http_json`/`http_csv` (GIS/planning) | `join` (demographic), `flag` (infra signals) |
| 20 | Tech Salary & Compensation | `http_csv`/aggregates | `aggregate` (regional premium), `join` (skill map) |
| 21 | Remote Work & Distributed Teams | `http_json`/`http_csv` (company, visa) | aggregate by sector, `seasonal_index`/pattern |
| 22 | Commodity Price Volatility | `http_json` (exchange), `http_csv` (USGS) | `volatility`, `corr`, `flag` (disruption) |
| 23 | Global Hosting Performance | `http_json`/`http_csv` (Geekbench etc.) | `minmax_normalize` (cost/perf matrix) |
| 24 | AI Model Performance | `paged_http_json` (HF), `http_json` (PapersWithCode) | `pct_change` (adoption velocity), aggregate (benchmarks) |
| 25 | Cross-Border EU Trade | `paged_http_json`/`http_csv` (customs) | `join`, `aggregate` (tariff impact), trend |
| 26 | Renewable Grid Status | `http_json` (grid operators) | `aggregate` (utilization), `flag` (stress) |
| 27 | Executive Movement / C-Suite | bespoke (filings, press) | aggregate (career patterns); network-mapping = **derived table only**, see limits |
| 28 | Programming Language Adoption | `paged_http_json` (GitHub), `http_json` (SO) | `pct_change` (velocity), `aggregate` by region/sector |
| 29 | Carbon Emission Trading | `http_csv`/bespoke (EU ETS) | `forecast`, `classify` (regulatory impact) |
| 30 | Municipal Tender & Procurement | `paged_http_json`/`http_csv` (portals) | `score` (opportunity), `aggregate` (supplier trends) |

**Result:** 30/30 covered. ~20 are config-only on `http_json`/`http_csv`/`paged_http_json`/
`jsonstat`/`sdmx`; the rest add a ~30-line bespoke adapter. Every "statistical
preprocessing" phrase in the catalog maps onto a named step or helper above.

---

## Explicit limits (honesty, not silent gaps)

- **Network / graph outputs** (dataset 27 "network mapping") — datavibes emits **tabular**
  snapshots. It can produce an edge-list / adjacency table, but rendering a graph
  visualization is a downstream (delivery-layer) concern, not this tool's.
- **Fragile-scrape sources** (13, 15, 16, 27, 30 partly rely on gazettes/filings/portals) —
  where no clean public API exists, the bespoke adapter is the fragile part and needs the
  health-check/staleness alert (backlog) more than the API-backed datasets do.
- **Auth-gated volume** (Comtrade, GitHub, ACS) — handled by `paged_http_json` + env-var
  tokens; rate limits are an operational concern for the cron, not a modelling gap.

---

## Derived backlog

- **S07 — Statistical primitive library + `join`/`paged_http_json`/`jsonstat`/`sdmx`**:
  build the closed set of adapters, steps, and helpers tabulated above, each TDD, each a
  pure/mocked unit test. After S07, datasets 1–30 are authorable as config (+ occasional
  small adapter) with **no further SDK change** — the acceptance criterion for "any dataset
  of the list renders on datavibes."
- Datasets themselves (S06 = #1, then #2…#30) each become a single `datasets/<slug>/`
  folder, prioritised by the product brief (Weather → Hosting → EU Jobs → OSS first).
