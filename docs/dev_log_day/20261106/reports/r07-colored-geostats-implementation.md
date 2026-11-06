# R07 — colored-geostats: thermomap framework + World Population Density (implemented)

**Date:** 2026-11-06 · **Type:** Implementation report · **Status:** done (nothing committed)
**Covers:** [s13](../done/s13-colored-geostats-thermomaps.md)
**Requirements:** [`../sprints/_engineering_requirements.md`](../sprints/_engineering_requirements.md)

---

## Summary

S13 is implemented TDD-first. The SDK now renders **SVG thermomaps** next to the CSV. It has
two registered colour scales, `sex-ratio-bivariate` and `spectral-density`. Two datasets
ship as pure config: `world-population-density` and `world-population-density-heat`. Both
ran **live** against the World Bank API: 217 countries, 170 of the 176 drawn shapes
matched, ~145 KB per SVG.

**Gate:** 187 tests pass (112 before + 75 new) with zero live network. One test was
already failing and still fails; see "Known issues".

---

## What was built

| Area | Files |
|---|---|
| Pure helpers | `processing/functions.py`: `scale_to_range`, `unit_normalize`, `normalization_domain`, `value_at_unit`, `complement`, `sex_majority`, `round_to` (all registered for `derive`) |
| Colour | `maps/color_math.py` (HSL→hex, sRGB lerp, stops), `maps/painting.py` (`Painting`, `Legend`, …), `maps/color_scales.py` (two scales) |
| Interface + registry | `interfaces.ColorScale` (one method), `COLOR_SCALE_REGISTRY` / `register_color_scale` / `resolve_color_scale`; `resolve_writer(name, options)` |
| Geometry | `maps/geometry.py` (manifest catalog, sha256 check, world/region/country selection), vendored `ne_110m_admin_0_countries.geojson` (Natural Earth v5.1.2, slimmed to 207 KB), `scripts/vendor_natural_earth.py`, `make geometry` |
| Projection | `maps/projection.py`: `equal-earth`, `equirectangular` (standard parallel) |
| Rendering | `maps/svg.py` (path/legend fragments), `maps/svg_writer.py` (`svg-map` writer + `<ts>.join.json`) |
| Plumbing | `DatasetConfig.outputs` / `OutputSpec`, `Exporter.export_outputs` (one shared timestamp), `DatasetSDK.run_outputs`, CLI `run` prints every path, `FileStore.latest_output(extension=)` |
| Source | `sources/worldbank_latest.py`: `worldbank-latest` (paging, `mrnev=1`, aggregates dropped, indicators merged per ISO3) |
| Datasets | `datasets/world-population-density/`, `datasets/world-population-density-heat/` (config only) |
| Tests | `test_map_helpers.py`, `test_color_scales.py`, `test_geometry_and_projection.py`, `test_svg_map_writer.py`, `test_dataset_world_population_density.py`, fixture geometry, 3 goldens |

---

## Live run (2026-11-06)

| | bivariate | heat |
|---|---|---|
| CSV rows | 217 | 217 (byte-identical to bivariate) |
| SVG | 149 KB | 144 KB |
| Data years | density 2024 (214 countries), 2023 (2), 2021 (1); female share 2025 | same |

**Join report** (identical for both):
- **Features without rows (6):** ATF, CYN (N. Cyprus), FLK, SAH (W. Sahara), SOL (Somaliland), TWN (Taiwan). The World Bank publishes nothing for these, so they render as "No data".
- **Feature with a missing value (1):** KOS. The World Bank has the sex ratio but no density.
- **Rows not drawn (47):** micro-states and small islands that have no 110m shape (MAC, SGP, HKG, MCO, BHR, MLT, …). They stay in the CSV.
- The aliases `SSD→SDS`, `PSE→PSX` and `XKX→KOS` resolve all the code mismatches I found.

---

## Deviations from the sprint plan

1. **`worldbank-latest` is built in**, not dataset-local. Two datasets use it, and a
   dataset's `sources.py` is only imported for that dataset. This follows S07's rule that
   a reusable adapter belongs in the SDK.
2. **The colour domain is every row of the dataset**, not only the drawn features. This
   settles open question 2 in favour of "map and CSV always agree". The cost is described
   under "Finding" below.
3. **The "No data" legend swatch is owned by the writer**, not the scale. The writer also
   uses that colour for features with no row.
4. **`round_to` helper added**, so published columns aren't `0.6625999246306395`.
5. **The full-world SVG isn't golden-compared.** It's checked for byte-stability across two
   runs plus structural asserts. The fixture SVGs and the dataset CSV *are* golden files.

## Finding: the spectral map rarely shows red

The domain includes micro-states that aren't drawn: Macao is 20,631/km², while the densest
*drawn* country, Bangladesh, is about 1,300/km². The top third of the scale (orange→red) is
therefore spent on countries nobody sees, and the world map reads mostly green/teal with
yellow in South Asia and Western Europe. The bivariate map is affected the same way, since
its saturation ceiling is Macao. Proposed follow-up: a writer option
`color_domain: drawn | all`. With `drawn`, the map uses the full range over what's visible,
and the CSV keeps the global value.

---

## Known issues

- **Two copies of datavibes.** This repo's `.venv` has an editable install pointing at
  `~/dantweb/vbwd-sdk-2/datavibes`. That copy is ahead of this one: it has S07 primitives,
  an S12 with 11 more datasets, and its own `sources/worldbank_latest.py` (`worldbank-indicator`).
  The bare `datavibes` command therefore runs *that* code. S13 lives in **this** repo
  (`~/dantweb/datavibes`, the July snapshot). The tests and the live run used this repo's
  code explicitly. **A decision is needed** on which repo is canonical, and whether to port
  S13 there (expect to reconcile with its `worldbank-indicator` adapter).
- **`test_cli_new_validate_run_flow` was already failing.** The repo's `.env` sets
  `DATAVIBES_OUTPUT_DIR=/app/var/datavibes/data_out`, a container path, and the CLI test
  inherits it. It passes with the env var overridden.
- **The VBWD `dataset` plugin and `.svg`/`.join.json` files.** Whether the plugin serves
  them is unconfirmed (sprint open question 1).

---

## Follow-up (same day): overpopulation threshold + white-based men/women map

- **`parameters.overpopulated_per_km2`** (default 1000, env override `OVERPOPULATED_PER_KM2`) is
  declared once per dataset file and YAML-anchored into:
  - a new CSV column **`overpopulated`** (bool), via the new `at_least` helper and a new
    `derive … params:` mapping;
  - the heat map's new **`saturate_above`** option. Red now means "≥ threshold", and the
    legend's top tick reads `≥ 1,000`.
- Live result at 1000/km²: **11 overpopulated** (MAC, MCO, SGP, HKG, GIB, BHR, MLT, MDV, BGD, SXM,
  BMU). **Bangladesh is the only one drawn** at 110m; the rest are micro-states. The heat map
  now uses its whole range: India is orange, and Western Europe, Nigeria and Japan are yellow.
  This resolves the "spectral map rarely shows red" finding above.
- **Men/women map:** fill = white → full blue/red by normalised density (it was HSL
  saturation, which greyed sparse countries). The map has a light ocean background
  (`#e9eef3`) and grey borders, so near-white countries stay visible.
- Tests: 201 pass (+14).
- Still open: the men/women intensity is still scaled up to Macao (20,631/km²). The same
  threshold could cap it if wanted.

---

## Rebase onto origin/main (S12)

The "two copies of datavibes" issue above is resolved: `origin/main` is canonical, and this
work is rebased onto it. Changes made during the rebase:
- **Renumbered** to S13 / R07, because S09–S12 and R03–R06 already exist upstream.
- **Adapter renamed** `worldbank-indicators` → **`worldbank-latest`**
  (`sources/worldbank_latest.py`). Upstream's `worldbank-indicator` returns one row per
  country per year for a `join`, but these maps need the latest non-empty value per
  country, and the two indicators come from different years.
- **`DatasetSDK.run`** keeps upstream's failed-source warnings and LLM reports, and now
  writes every declared output (`run_outputs`).
- **`FileStore.latest_output(extension=)`** was re-added on top of upstream's
  snapshot-name filter.
- **Output paths** follow upstream's default `slug` layout: `output/<slug>/<ts>.*`.
- Tests: 308 pass (219 upstream + 89 S13).
