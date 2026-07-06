# 2026-07-04 — Dev day status (`datavibes`)

> First dev day of the standalone **`datavibes`** repo — a config-driven toolkit
> that collects data and generates versioned dataset snapshots for the "fully automated,
> zero-support" dataset product model.
> **Requirements:** [`sprints/_engineering_requirements.md`](sprints/_engineering_requirements.md)
> **Reports (this day):**
> - [r01 — 30-dataset catalog coverage on datavibes](reports/r01-dataset-catalog-coverage.md)
> - [r02 — implementation, config layer & live validation (112 tests, 397-row live run)](reports/r02-implementation-config-live-validation.md)

---

## Theme

Stand up the **dataset-generation SDK** so every future dataset (Phase 1 Hosting
Benchmarks, Phase 2 EU Tech Job Market, …) is **declarative config + a tiny optional
adapter**, not a bespoke script. The SDK owns the whole pipeline once
(sources → generator → processor → exporter); datasets own only `dataset.yaml`.

The tool is intentionally narrow: **CLI-only + importable, no server / DB / billing.**
Delivery, entitlements and billing stay in the VBWD `dataset` plugin, which consumes the
files written here. Output path matches the plugin's served shape:
`output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv`.

---

## Sprints

| Sprint | Title | Status |
|---|---|---|
| [s01](sprints/s01-dataset-generator.md) | Dataset Generator scaffolding — architecture (umbrella) | 🟡 PLANNED |
| [s02](sprints/s02-core-services-models-interfaces.md) | Core: services, models & interfaces (schema, config, registries, store, clock, facade+CLI) | 🟡 PLANNED |
| [s03](sprints/s03-generator-and-sources.md) | Generator & source adapters (`static`/`http_json`/`http_csv` → raw snapshot) | 🟡 PLANNED |
| [s04](sprints/s04-processor-and-steps.md) | Processor & steps (normalize/dedupe/derive/aggregate/validate) | 🟡 PLANNED |
| [s05](sprints/s05-exporter-and-writers.md) | Exporter & writers (csv/json/parquet → delivery-contract path) | 🟡 PLANNED |
| [s06](sprints/s06-first-dataset-us-regional-weather.md) | First dataset: **US Regional Weather & Climate Trends** (config + one adapter) | 🟡 PLANNED |
| [s07](sprints/s07-statistical-primitive-library.md) | Statistical primitive library + join/paged/stat-format adapters — **covers all 30 catalog datasets** | 🟡 PLANNED |
| [s08](sprints/s08-datasources.md) | Data sources for US Regional Weather — exact **free API-only** endpoints (NCEI/NOAA/OpenWeatherMap) + request/response examples | 🟡 PLANNED |
| [s09](sprints/s09-dataset-energy-renewable-share.md) | Dataset **#8 Energy → Renewable Share** — `worldbank-indicator` adapter + S07 `join`/`cagr`/`score` | ✅ DONE (2026-07-06) |
| [s10](sprints/s10-dataset-vehicle-production-ev-share.md) | Dataset **#9 Vehicle Production → EV Share** — `iea-ev` pivot adapter + S07 `sort`/`cagr`/`corr` | ✅ DONE (2026-07-06) |
| [s11](sprints/s11-dataset-hosting-cloud-pricing.md) | Dataset **#10 Hosting & Cloud Pricing** — `cloud-price-list` adapter (AWS/Azure keyless) + S07 `ratio`/`minmax_normalize` | ✅ DONE (2026-07-06) |

Build order: **s02 → s03 → s04 → s05** implement the SDK layer-by-layer (each TDD, each
green from a cold clone). **s06** authors the first real dataset as pure config + one small
adapter — the acceptance test for the "config, not code" design. **s07** builds the finite,
shared primitive library (adapters + steps + helpers) that [r01](reports/r01-dataset-catalog-coverage.md)
proves covers **all 30** catalog datasets, so datasets #2–#30 are each just a
`datasets/<slug>/` folder with **no SDK change**. **s09–s11** are the first of those
#2–#30 datasets authored on the S07 library: #8 Energy→Renewable Share and #9 Vehicle
Production→EV Share are **pure config**; #10 Hosting & Cloud Pricing is the "bespoke where
needed" case (one small keyless price-list adapter). All three are **blocked on S07** —
missing primitives are fixed there, never patched into a dataset.

---

## Backlog (carried forward)

- **s09–s11 IMPLEMENTED 2026-07-06** — datasets #8/#9/#10 shipped green (145 tests). Built the
  **S07 primitive subset** they need (not the whole S07 sprint): helpers `ratio`/`share`/
  `penetration`/`cagr`/`corr`/`minmax_normalize`/`volatility`; steps `sort`/`join`/`score`;
  grouped `derive` (`by:` → per-entity windows). Each dataset ships **one small `sources.py`
  adapter** (the real APIs are nested/long-format — same reason weather needed `ncei-climate`),
  processing is pure config. **Prereq fixed:** `datavibes/store/filestore.py` was missing from
  the initial commit (un-importable SDK) — reconstructed from its test contract to restore the
  112-test baseline. Full S07 (`paged_http_json`/`jsonstat`/`sdmx` adapters, `flag`/`classify`/
  `forecast`/`gini`/`hhi`/etc.) still pending for later datasets.
- **Next datasets (#2–#7, #11–#30)** — same one-folder template; author on demand from the
  [r01 coverage matrix](reports/r01-dataset-catalog-coverage.md) (EU Tech Job Market, OSS
  Health, Air Quality next per the product-brief priority).
- **Health checks** — staleness alerts (snapshot > N days old), row-count sanity.
- **CI** — cold-clone `pip install -e .` + `run` fixture dataset, network-mocked.
- **GitHub Actions cron** — daily `datavibes run <slug>` + snapshot commit/upload.

---

## Notes

- Folder name is `datavibes` (as specified).
- Related: [[project_s110_datasets_plugin]] (the consumer), product brief 2026-07-04
  (2-tier pricing, zero-support automation rules).
