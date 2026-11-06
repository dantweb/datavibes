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

- **S14 — city dot maps** · [sprint](done/s14-city-dot-maps.md) · [results](reports/r08-city-dot-maps.md)
  - `svg-dot-map` writer (one dot per city ≥ 100,000, area ∝ population, same colour
    scales), `sparql` source, `lookup` step, `null_outside` helper.
  - `world-city-population-density` (country sex majority × city density) and
    `-heat` (city density, red ≥ 10,000/km²). Live: 4,017 cities of ≥ 100k. Those that
    can't be coloured are excluded, leaving 3,236 cities on the men/women map and 3,255 on
    the heat map. Every map legend now has a **Coverage** block (shown / not included and
    why), fed by run provenance from reasoned `filter` steps. 335 tests pass. Uncommitted.

- **Documentation + licence:** `docs/managing-datasets.md` (operations, config,
  scheduling, troubleshooting, catalog of 19 datasets), `docs/creating-datasets.md`
  (tutorial; its five example configs were extracted and run live), `docs/reference.md`
  (every primitive), `docs/README.md` index. `LICENSE`: BSL 1.1, with production use
  free below 1 BTC annual revenue; Apache 2.0 from 2030-11-06.

## Carried forward

- **Licence parameters to confirm:** Licensor "vbwd", Change Date 2030-11-06, Change
  License Apache 2.0, and the contact URL were chosen as defaults.

- **City data quality:** wrong Wikidata areas inside the 10–60,000/km² bounds; metro areas
  typed as cities; XKS/XKX alias for `lookup` ([r08](reports/r08-city-dot-maps.md)).

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
