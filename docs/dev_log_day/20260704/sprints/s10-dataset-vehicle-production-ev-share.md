# S10 — Dataset: Vehicle Production → EV Share (catalog #9)

**Date:** 2026-07-06 · **Type:** Sprint plan + data-source spec · **Status:** ✅ DONE (2026-07-06)

> **As-built note.** Shipped as `datasets/vehicle-production-ev-share/` (`dataset.yaml` +
> `sources.py`) green under `pytest`. IEA `/evs` is **long-format** (one row per
> `parameter`) keyed by region *name* with no ISO3, so a ~60-line `iea-ev` adapter pivots
> parameters → columns (`ev_sales`/`ev_share_pct`/`charging_points`), summing powertrains,
> and grouping is by **country name** (schema dropped `iso3`). Processing is pure config on
> the S07 subset: `sort` (country,year) → grouped `derive: cagr(ev_share_pct, years=5)` →
> grouped `derive: corr(ev_share_pct, charging_points)`. `ev_share_pct` comes straight from
> IEA's published share, so `penetration()`/total-sales denominator weren't needed;
> OICA/OWID/World-Bank sources dropped for v1.
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md)
(public-sources-only: **free, documented HTTP APIs, no scraping**).
**Depends on:** the full SDK (S02–S05) **and the S07 primitive library** — authored as
**config only**. No SDK code; **no bespoke adapter** if S07's `http_json`/`http_csv` cover
the sources (they do).
**Catalog basis:** [`../reports/r01-dataset-catalog-coverage.md`](../reports/r01-dataset-catalog-coverage.md) row 9.
**Template:** [`s06-first-dataset-us-regional-weather.md`](s06-first-dataset-us-regional-weather.md).

**Trigger.** Third production dataset — pairs total vehicle output with the electric share
and its growth, so buyers can see the ICE→EV transition per market.

---

## Dataset brief

| Field | Value |
|---|---|
| **Topic** | Vehicle Production & Sales → EV Share |
| **Data sources (free APIs)** | IEA Global EV Data (no key), Our World in Data CSV (no key), World Bank Indicators (no key) |
| **Statistical preprocessing** | EV **penetration**, **CAGR** (adoption speed), **correlation** of EV share vs charging infrastructure |
| **Value proposition** | Market-by-market EV-transition intelligence for the auto supply chain |
| **Target buyers** | Auto OEMs & suppliers, battery makers, charging networks, mobility investors |
| **Update regularity** | Daily snapshot (underlying series annual; cron re-cuts latest) |
| **Size per update** | 2–6 MB |

---

## The whole developer experience

```
datasets/vehicle-production-ev-share/
└── dataset.yaml        # metadata + schema + sources + processing — NO sources.py
```
```bash
datavibes new vehicle-production-ev-share --category mobility
datavibes validate vehicle-production-ev-share && datavibes run vehicle-production-ev-share
```

### `dataset.yaml`
```yaml
metadata:
  slug: vehicle-production-ev-share
  title: Vehicle Production & Sales — EV Share & Adoption Speed
  category: mobility
  license: "IEA terms (free data); OWID CC-BY-4.0; World Bank CC-BY-4.0"
  update_frequency: daily
  attribution: "IEA Global EV Data Explorer; Our World in Data; World Bank Open Data"

schema:
  - { name: country,            dtype: str }
  - { name: iso3,               dtype: str }
  - { name: year,               dtype: int }
  - { name: ev_sales,           dtype: float, unit: "vehicles", nullable: true }
  - { name: total_car_sales,    dtype: float, unit: "vehicles", nullable: true }
  - { name: ev_share_pct,       dtype: float, unit: "%",  description: "EV % of new car sales" }
  - { name: charging_points,    dtype: float, unit: "count", nullable: true }
  - { name: ev_cagr_5y,         dtype: float, unit: "%",  nullable: true, description: "5y CAGR of EV share" }
  - { name: ev_infra_corr,      dtype: float, nullable: true, description: "corr(EV share, charging points)" }

sources:
  # A — IEA Global EV Data (JSON) — EV sales, stock, sales share, charging points.
  - type: http_json
    url: https://api.iea.org/evs
    select: "$[*]"
    params: { parameters: "EV sales,EV sales share,EV charging points", category: Historical, mode: Cars, csv: false }
  # B — Our World in Data — electric car sales share (bulk CSV), no key.
  - type: http_csv
    url: https://ourworldindata.org/grapher/electric-car-sales-share.csv?v=1&csvType=full
    select: "$"
  # C — World Bank motor-vehicle context (per-1000 people), no key — optional denominator.
  - type: http_json
    url: https://api.worldbank.org/v2/country/all/indicator/IS.VEH.NVEH.P3
    select: "$[1][*]"
    params: { format: json, per_page: 20000, date: "2000:2024" }

processing:
  - normalize                                              # IEA long-form → wide (parameter → column)
  - join:      { on: [iso3, year], how: outer }            # A ⨝ B ⨝ C on country-year
  - derive:    { column: ev_share_pct,  expr: "penetration(ev_sales, total_car_sales)" }
  - derive:    { column: ev_cagr_5y,    expr: "cagr(ev_share_pct, years=5)" }
  - derive:    { column: ev_infra_corr, expr: "corr(ev_share_pct, charging_points)" }
  - validate
```

**Every promise → an existing S07 primitive:**

| Dataset promise | S07 step/helper |
|---|---|
| EV **share / penetration** | `penetration(part, whole)` |
| **Adoption speed** | `cagr(col, years)` |
| EV-vs-infrastructure **correlation** | `corr(col_a, col_b)` |
| Cross-source country-year merge | `join` |

No new SDK primitive required — all four are in the r01 primitive library built by S07.
**S10 is blocked on S07** if any is missing; fix it in S07, never here.

---

## Data sources (all free, all API/CSV over HTTPS — no scraping)

| Src | Base URL | Auth | Role |
|---|---|---|---|
| A | `https://api.iea.org/evs` | **none** | EV sales, sales share, charging points (backbone) |
| B | `https://ourworldindata.org/grapher/electric-car-sales-share.csv` | **none** | EV sales-share cross-check / gap-fill |
| C | `https://api.worldbank.org/v2/country/all/indicator/IS.VEH.NVEH.P3` | **none** | Vehicle-fleet context (optional) |

**A — IEA Global EV Data Explorer API** (the JSON the public explorer itself calls)
```bash
curl -G 'https://api.iea.org/evs' \
  --data-urlencode 'parameters=EV sales' \
  --data-urlencode 'category=Historical' \
  --data-urlencode 'mode=Cars' \
  --data-urlencode 'csv=false'
```
```json
[ {"region":"Germany","category":"Historical","parameter":"EV sales","mode":"Cars",
   "powertrain":"BEV","year":2023,"unit":"Vehicles","value":524219},
  {"region":"Germany","category":"Historical","parameter":"EV sales share","mode":"Cars",
   "powertrain":"EV","year":2023,"unit":"percent","value":18.4} ]
```
→ built-in `http_json`, `select: "$[*]"`; `normalize` pivots the long-form
`parameter → {ev_sales, ev_share_pct, charging_points}` and maps `region → country/iso3`.

**B — OWID grapher CSV** (`Entity, Code, Year, <metric>`) → `http_csv`; supplies EV sales
share where IEA is sparse; `join` reconciles, `dedupe`-style outer join keeps the richer value.

> **Note on OICA:** OICA production totals are published only as spreadsheets/HTML tables (no
> clean API) — **excluded** to honour the no-scraping rule. Total-sales denominators come from
> IEA (`EV sales` ÷ `EV sales share`) and OWID; if a genuine production API appears it can be
> added later as a `http_csv` source without touching the pipeline.

---

## What this sprint adds to the SDK

**Nothing.** Config only. A missing `penetration`/`cagr`/`corr`/`join` is an S07 bug.

## Tests
- **End-to-end fixture run**: recorded IEA JSON + OWID CSV bodies → golden CSV at the
  contract path, byte-stable under `FixedClock`, exact schema columns.
- **IEA long→wide pivot**: a fixture with `EV sales`, `EV sales share`, `EV charging points`
  rows for one country-year collapses to a single wide row with all three columns set.
- **Derive values**: hand-computed `penetration` / `cagr(5y)` / `corr` for one market match
  pipeline output.
- **No-denominator path**: a country with EV share but no `total_car_sales` still yields a
  valid row (share taken directly from IEA `EV sales share`).

## Scope
**IN:** the `vehicle-production-ev-share/` dataset folder (config only) + fixture tests.
**OUT:** any SDK/primitive code (S07), OICA production ingestion (blocked on a public API),
GitHub Actions cron (shared follow-up).

## Definition of done
- [ ] `datavibes validate vehicle-production-ev-share` passes; `run` writes
      `output/mobility/vehicle-production-ev-share-<hash>/<ts>.csv`.
- [ ] **Zero** SDK/adapter code added — pure config.
- [ ] Fixture end-to-end + pivot + derive tests green with **zero** live network.
- [ ] Golden CSV byte-stable under a fixed clock; a valid snapshot is produced from the
      no-key sources alone.
