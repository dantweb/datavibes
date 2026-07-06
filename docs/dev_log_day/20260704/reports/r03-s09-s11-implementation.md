# R03 — s09–s11 implementation: catalog datasets #8/#9/#10 + S07 primitive subset

**Date:** 2026-07-06 · **Type:** Implementation report · **Status:** ✅ DONE
**Sprints:** [s09](../sprints/s09-dataset-energy-renewable-share.md) ·
[s10](../sprints/s10-dataset-vehicle-production-ev-share.md) ·
[s11](../sprints/s11-dataset-hosting-cloud-pricing.md)
**Basis:** [r01 catalog coverage](r01-dataset-catalog-coverage.md) rows 8–10.

**Outcome.** Datasets **#8 Energy → Renewable Share**, **#9 Vehicle Production → EV Share**,
and **#10 Hosting & Cloud Pricing** are implemented and green — **145 tests pass**, zero live
network. Each is a `datasets/<slug>/` folder (config + one small adapter) authored on a newly
built **subset of the S07 primitive library**. Two pre-existing repo defects that blocked all
work were found and fixed along the way.

---

## Blockers found & fixed first

1. **Missing core module — the SDK didn't import.** `datavibes/store/filestore.py`
   (`FileStore`, used by generator / exporter / SDK / conftest) was absent from disk and
   never committed, so `import datavibes` crashed and **no test could run**. Reconstructed
   faithfully from its full test contract (`tests/test_store.py`) + call sites; this restored
   the **112-test baseline** exactly (matching [r02](r02-implementation-config-live-validation.md)).

2. **Root cause — an unanchored `.gitignore` rule.** `.gitignore` carried a bare `store/`
   (intended for the runtime output tree) that silently matched the **`datavibes/store/`
   package** as well — which is why the module never made it into the initial commit.
   Fixed by anchoring the runtime trees to the repo root (`/store/`, `/output/`, `/data_out/`)
   so the package is tracked while runtime output stays ignored. Verified with
   `git check-ignore`.

---

## S07 primitive subset built (not the whole S07 sprint)

Only the primitives datasets #8–#10 require — each pure, each unit-tested
(`tests/test_s07_primitives.py`).

| Kind | Added | Purpose |
|---|---|---|
| helper | `ratio(a, b)` | elementwise `a/b` (null/zero-safe) |
| helper | `share` / `penetration` | part as **percent** of whole |
| helper | `cagr(series, years)` | compound annual growth %, trailing lag |
| helper | `corr(a, b)` | static Pearson, broadcast (→ per-group with grouped derive) |
| helper | `minmax_normalize(series, invert)` | scale to `[0,1]`; invert for price/perf |
| helper | `volatility(series, window)` | rolling sample std |
| step | `sort` | stable order before windowed derives + byte-stable output |
| step | `join` | outer coalesce of source rows by key (one row per key) |
| step | `score` | weighted min-max composite index |
| step | `derive` (extended) | optional `by:` → apply helper **per entity** (windows never span groups) |

Full S07 (`paged_http_json` / `jsonstat` / `sdmx` adapters, `flag` / `classify` / `forecast` /
`gini` / `hhi` / `zscore` / `seasonal_index`) remains for later catalog datasets.

---

## Datasets shipped

| # | Slug | Adapter | Processing (config, on S07) |
|---|---|---|---|
| 8 | `energy-renewable-share` | `worldbank-indicator` (nested JSON, paged) | `join` → grouped `cagr` → `score` |
| 9 | `vehicle-production-ev-share` | `iea-ev` (long-format → wide pivot) | `sort` → grouped `cagr` → grouped `corr` |
| 10 | `hosting-cloud-pricing` | `cloud-price-list` (AWS bulk + Azure OData paging + specs CSV) | `dedupe` → `sort` → `ratio` → `minmax_normalize` |

All three fetch **free, keyless APIs** (World Bank Open Data, IEA Global EV Data, AWS Price
List, Azure Retail Prices) — no scraping, no secrets.

### Honest deviations from the sprint drafts
- **s09/s10 are not "zero code."** The real APIs are nested (World Bank `[meta,[records]]`)
  or long-format (IEA parameter rows), which the generic `http_json`/`http_csv` can't map to
  schema columns — so each needs a ~30–60-line `sources.py` adapter, exactly the r01
  "per-dataset adapter is the exception" case (as weather needed `ncei-climate`). Processing
  stays pure config.
- **s10 keys on country name** (IEA carries no ISO3); `iso3` dropped from the schema.
- **s11 dropped `price_volatility` for v1** — it's a rolling std *across* daily snapshots,
  which a single `run` cannot compute; it populates once ≥2 snapshots exist. The `volatility`
  helper is built and unit-tested regardless.
- **YAML gotcha:** the `join` key must be quoted (`"on"`) — a bare `on:` parses as boolean
  `true`.

---

## Verification

- `pytest` → **145 passed** (112 baseline + 33 new: 17 primitive, 7 s09, 6 s10, 7 s11), no
  live network; every end-to-end run is **byte-stable** under a fixed clock and emits exactly
  the declared schema columns.
- Sanity eyeball (energy, Germany): renewable share 30→55 %, `renewable_cagr_5y` blank until
  the 5-year lag then `(55/30)^(1/5)−1 = 12.89 %`, `transition_score` 33→100.
- `DatasetSDK.list()` discovers all four datasets; `validate` passes for each.

## Definition of done — met
- [x] Each dataset `validate`s and `run`s to `output/<category>/<slug>-<hash>/<ts>.csv`.
- [x] Processing is pure config on shared S07 primitives; per-dataset code is one small adapter.
- [x] Adapter + end-to-end fixture tests green with **zero** live network; output byte-stable.
- [x] SDK import restored; `.gitignore` root cause fixed so the store package is committed.
