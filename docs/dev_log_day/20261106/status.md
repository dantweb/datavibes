# 2026-11-06 — status

> Carried forward from [`../20260811/status.md`](../20260811/status.md).
> **Requirements:** [`sprints/_engineering_requirements.md`](sprints/_engineering_requirements.md)

## Done today

- **S13 — `colored-geostats` thermomaps** ·
  [sprint](done/s13-colored-geostats-thermomaps.md) ·
  [results](reports/r07-colored-geostats-implementation.md)
  - New map framework `datavibes/maps/`: a `ColorScale` registry with
    `sex-ratio-bivariate` (white → full blue/red by density) and `spectral-density`
    (dark blue → green at the average → red, plus a `saturate_above` threshold).
    Vendored, sha256-checked Natural Earth 110m geometry; equal-earth and equirectangular
    projections; an `svg-map` writer with a legend and a `<ts>.join.json` join report.
  - A dataset can declare `outputs:` (csv + svg-map …, one timestamp per run). New
    `worldbank-latest` source (latest non-empty value per country). Derive helpers
    `scale_to_range`, `complement`, `sex_majority`, `at_least`, `round_to`, plus
    `derive … params:`.
  - Datasets `world-population-density` and `world-population-density-heat`, both
    authored as config only and run live (217 countries). `parameters.overpopulated_per_km2`
    (default 1000, env `OVERPOPULATED_PER_KM2`) drives the CSV `overpopulated` flag and
    the red end of the heat map.
  - Rebased onto S12 (`origin/main`). `pytest -q` is green at 308 tests (89 new) when
    `DATAVIBES_OUTPUT_DIR` is overridden; see the `.env` item below.
  - The `dev_log_day` skill now points at `docs/dev_log_day/` (it pointed at `docs/dev_log/`).

## Carried forward

- **Map colour domain:** the men/women map's intensity still tops out at Macao
  (20,631/km², not drawn at 110m). Options: cap it at the overpopulation threshold, or add
  `color_domain: drawn | all` to `svg-map`.
- **VBWD plugin:** confirm it serves `.svg` + `.join.json` from a snapshot folder.
- **`test_cli_new_validate_run_flow` fails locally:** it inherits the local `.env`'s
  container `DATAVIBES_OUTPUT_DIR`. Isolate the test from `.env`.
- **Region/country map datasets:** the framework supports them; admin-1 geometry
  (≈ 40 MB at 10m) needs a fetch-and-cache decision.
- *From 2026-08-11:* #23 Global Hosting Performance (no keyless feed) ·
  `us-regional-weather` has no data until `NCDC_WEB_SERVICE_TOKEN` is set · #2 US Census
  needs a key · #16/#30/#13 procurement/regulatory sources need their own sprint · snapshot
  regression alarm · `sdmx` adapter deferred.
