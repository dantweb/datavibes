# R08 — City dot maps: results

**Date:** 2026-11-06 · **Covers:** [s14](../done/s14-city-dot-maps.md) · **Status:** done (uncommitted)

## Live run
| | value |
|---|---|
| Cities ≥ 100,000 (Wikidata) | **4,017** |
| With a usable density | 3,255 (762 have no area, or one outside 10–60,000/km²) |
| Overpopulated (≥ 10,000/km²) | 239 |
| Without World Bank country data | 20 (ESH, TWN, XKS) |
| SVG size | ~1.1 MB per map |
| Query time | ~15 s cold, ~1 s cached |

Tests: 327 pass (+19). Network is mocked; goldens: `fixture_dots.svg`,
`world_city_population_density.csv`.

## Findings
- **Query cost is close to Wikidata's 60 s limit.** With the label service inside the
  grouped query it took 11–55 s depending on load, and a `FILTER NOT EXISTS` on
  dissolution dates gave a 504. Resolving labels outside the grouped subquery brought a
  cold run to ~15 s. `sparql` has its own 90 s timeout, because the SDK-wide 30 s timeout
  turned a slow query into a "green" run with an empty map.
- **Historical countries:** Wikidata keeps both, e.g. USSR and Russia, as a city's
  country. The withdrawn ISO 3166-3 codes are filtered out.
- **Data quality:** some Wikidata areas are wrong. Outside 10–60,000/km² the density is
  nulled. Some suspicious values remain inside that range (Shahrisabz 59k/km², Akçakale
  58k/km²). Some "cities" are really municipalities or metro areas (Chongqing 32M, "New York
  metropolitan area").
- **Kosovo:** Wikidata uses `XKS`, the World Bank `XKX`, so its cities miss country data.
  `lookup` has no alias map yet.

## Open
- Tighten the density bounds, or cross-check against GeoNames population.
- An alias map for `lookup` (XKS → XKX).
- Option: drop metro-area entities (P31 = Q1907114) to avoid double counting.

## Follow-up: cities with no data are excluded

A `filter` step drops every city whose dot can't be coloured. These cities are no longer
in the CSV or on the map:
- **Men/women map:** needs a usable density **and** a country sex ratio → **3,236 cities**.
- **Heat map:** needs only a usable density → **3,255 cities**. It keeps 19 cities (Taiwan,
  Western Sahara, Kosovo) that have no World Bank sex ratio.
- 762 cities (no Wikidata area, or one outside 10–60,000/km²) are excluded from both.
- The dot maps' legend shows "No data" only when a drawn dot lacks a colour, which is now
  never. On country maps it stays.
- The two city datasets' CSVs now differ by those 19 rows.

## Follow-up: coverage legends on every map

Every map legend ends with a **Coverage** block (live, 2026-11-06):

| Map | Coverage |
|---|---|
| world-population-density (both) | Countries coloured: 169 of 176 drawn · Without data (grey): 7 · In the data but not drawn: 47 |
| world-city-population-density | Cities shown: **3,236 of 4,017** · Not included: 781 — no usable density (missing or implausible area): 762 · no country sex-ratio data: 19 |
| world-city-population-density-heat | Cities shown: **3,255 of 4,017** · Not included: 762 — no usable density (missing or implausible area): 762 |

How: `filter` takes an optional `reason`. `Processor.process_with_provenance` records
rows dropped per reasoned step, and the exporter passes that `Provenance` to every writer
via `Writer.attach_provenance` (default no-op). Map writers print it, and `<ts>.join.json`
carries `excluded`. Tests: 335 pass (+8).
