# R04 — S12 dataset batch: live-run results

**Date:** 2026-08-11 · **Type:** run evidence · **Status:** reference
**Sprint:** [`../sprints/s12-catalog-primitives-and-datasets.md`](../sprints/s12-catalog-primitives-and-datasets.md)

Every dataset below was authored as **config only** on the S12 primitive library and
then executed live (`datavibes run <slug>`) against its real public source. The row and
column counts are from the produced `output/<slug>/<timestamp>.csv`.

## What shipped

| Catalog # | Slug | Rows | Cols | Coverage | Source |
|---|---|---:|---:|---|---|
| 24 | `ai-model-performance` | 500 | 17 | top 500 Hub models by 30-day downloads | Hugging Face Hub API |
| 12 | `oss-project-health` | 55 | 25 | 55 projects (20 npm · 20 PyPI · 15 infra) | GitHub REST + npm + pypistats |
| 28 | `programming-language-adoption` | 24 | 16 | 24 languages | GitHub Search + Stack Exchange |
| 11 | `eu-tech-job-market` | 412 | 14 | ~37 geographies × 2015-2025 | Eurostat `jvs_a_rate_r2`, `isoc_sks_itspt` |
| 20 | `tech-salary-compensation` | 208 | 16 | ~35 geographies × 2020-2025 | Eurostat `lc_lci_lev`, `tec00114` |
| 4 | `eu-economic-demographic` | 592 | 16 | ~54 geographies × 2010-2025 | Eurostat `tps00001`/`tec00114`/`tec00118`/`une_rt_a` |
| 3 | `air-quality-pollution` | 5 760 | 23 | 30 cities × 192 hours | Open-Meteo Air Quality (CAMS) |
| 26 | `renewable-grid-status` | 2 920 | 15 | 8 countries × 365 days | energy-charts daily-average shares |
| 17 | `carbon-emissions-trajectory` | 12 896 | 19 | 204 countries × 1960-2024 | OWID Global Carbon Budget + World Bank |
| 5 | `world-bank-global-development` | 6 317 | 19 | 257 economies × 2000-2024 | World Bank Indicators |
| 22 | `power-price-volatility` | 1 268 | 14 | 14 bidding zones × 96 quarter-hours | energy-charts day-ahead spot |

## Spot checks (do the numbers mean anything?)

- **carbon-emissions-trajectory, 2023** — China 12.17 Gt (33.1% of world), United States
  4.92 Gt (13.4%), India 3.06 Gt (8.3%). Matches the Global Carbon Budget headline
  figures. The `forecast` step projects the US *down* to 4.56 Gt and India *up* to
  3.34 Gt by 2028 on a 10-year trend — directionally the right story for both.
- **world-bank-global-development, 2023** — cross-country Gini of GDP per capita = 0.641,
  the expected magnitude for unweighted between-country income dispersion.
- **programming-language-adoption** — JavaScript 46.4M repos / 2.52M SO questions,
  Python 32.3M / 2.21M; cohort HHI 0.16, Gini 0.71 — a moderately concentrated field
  with a long niche tail, which is what the ecosystem actually looks like.
- **oss-project-health** — 54/55 projects pushed within 30 days; the single `watch`-class
  project is MinIO at 108 days and it is correctly flagged `is_stale`.
- **air-quality-pollution** — 228 of 5 070 city-hours with a full 24-hour window exceed
  the WHO 2021 PM2.5 daily guideline (15 µg/m³).
- **power-price-volatility** — the shape of the European market falls straight out:
  hydro-rich Nordics cheapest (FI mean €5.61/MWh, SE4 €36.20), import-dependent
  IT-North dearest (€179.54), and 42 negative-price intervals concentrated in the
  solar-heavy DE-LU / NL / PL zones (PL bottoming at −€22.87). Nothing here was
  hand-tuned — `classify`, `volatility` and `flag` produced it from the raw series.

## Failures worth recording

1. **A throttled source produced a green, empty CSV — twice.** The generator degrades a
   failing source to zero rows on purpose (LSP), and `run` printed nothing, so
   `world-bank-global-development` and `carbon-emissions-trajectory` both "succeeded"
   with 0 rows. Two fixes landed: `run` now names failed sources on stderr, and
   `worldbank-indicator` paces its indicator/page loop. **Remaining gap:** a row-count
   collapse against the previous snapshot should fail the run, not warn.
2. **429 was not treated as transient.** Every polite public API in this batch meters
   callers. `request_with_retry` now retries 429, and the default retry budget went to
   5 attempts / 2 s linear backoff. Before that fix `renewable-grid-status` was silently
   losing two-thirds of its solar and wind columns; after it, all three share columns
   are complete for all 8 countries.
3. **Hugging Face drops fields from a *sorted* listing.** `author` and `lastModified`
   come back null unless `full=true` accompanies `sort` — which silently voided the
   entire maintenance-class column on the first run.
4. **Eurostat aggregate codes are not interchangeable.** `lc_lci_lev` publishes almost
   nothing for `nace_r2=B-S` (5 values) but is fully populated for `B-S_X_O` (290).
   Always count values before trusting a dimension code.
5. **Uneven time axes break windowed helpers.** `lc_lci_lev` runs 2012, 2016, then
   annually — so a `cagr(years=3)` over *row positions* is not a 3-year growth rate.
   The dataset was cut to 2020+ where the axis is uniform.

## Report bundles

Every dataset ships the same deliverable shape as `vehicle-production-ev-share`:

```
output/<slug>/
├── <YYYY-MM-DD-HH-MM>.csv     the snapshot
├── charts/NN-<title>.png      one PNG per declared chart
├── analytics.md               LLM-authored read of the numbers
├── statistics.md              LLM-authored methodology + limitations
└── report.pdf                 both, with the charts embedded
```

The reporter was pointed at **Claude Opus 5** (`llm.provider: anthropic`) — the
configured DeepSeek key in `.env` was a one-character placeholder, so every prior
report had silently degraded to the profile-only fallback. `max_tokens` went to
16 000 because Opus 5 thinks by default and that budget covers thinking *and*
prose. `llm.enabled` is now `true`, so `datavibes run` authors the bundle itself
and a cron produces the full deliverable without a second command.

Prose is grounded in a deterministic `DatasetProfile` (real row counts and column
statistics), never in free recall — the reports name the coverage gaps
(`task` populated for 454/500 Hub models) rather than papering over them.

## Not shipped, and why

`#23 Global Hosting Performance` (no keyless benchmark feed), `#2 US Census`
(`api.census.gov` now requires a key), `#16`/`#30`/`#13` procurement and regulatory
(POST-search and gazette scrapes — own sprint), and the `sdmx` adapter (no reachable
endpoint left that needs it). Detail in the sprint doc.
