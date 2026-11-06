# S14 — City dot maps (one dot per city ≥ 100,000)

**Date:** 2026-11-06 · **Type:** Sprint (planned and built the same day) · **Status:** ✅ DONE — see [r08](../reports/r08-city-dot-maps.md)
**Requirements:** [`../sprints/_engineering_requirements.md`](../sprints/_engineering_requirements.md)
**Builds on:** [s13](s13-colored-geostats-thermomaps.md) (map framework, colour scales).

## Ask
A more detailed map: one dot per city, dot size = city size, the same two colour schemes,
and every city of 100,000+ people.

## Decisions (user-confirmed 2026-11-06)
- **Men/women colour:** the **country's** sex majority. Open data has a city-level split
  for only ~321 of ~4,000 cities (Wikidata P1539/P1540). Intensity = the city's own density.
- **Heat colour:** the city's own density (population ÷ area, from Wikidata).

## Built
- `sparql` source (generic SPARQL 1.1, Wikidata default, 90 s timeout).
- `lookup` step: one-to-many enrichment by key from another source's rows. Upstream's
  `join` coalesces rows per key, so it can't be used here.
- `null_outside` helper, for implausible crowd-sourced values.
- `svg-dot-map` writer: a subclass of `svg-map` via a new `_build_layers` hook. Area ∝
  value, a size legend, and a point report.
- `ratio_label` option on `sex-ratio-bivariate`.
- Datasets `world-city-population-density` and `world-city-population-density-heat`.
