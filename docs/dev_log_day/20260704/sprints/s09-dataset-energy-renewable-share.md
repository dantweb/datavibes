# S09 — Dataset: Energy → Renewable Share (catalog #8)

**Date:** 2026-07-06 · **Type:** Sprint plan + data-source spec · **Status:** ✅ DONE (2026-07-06)

> **As-built note.** Shipped as `datasets/energy-renewable-share/` (`dataset.yaml` +
> `sources.py`) green under `pytest`. The "zero code / pure config" target below was
> **not** met: World Bank returns a nested `[meta,[records]]` envelope with page paging,
> so it needs a ~55-line `worldbank-indicator` adapter (mapping each indicator → one schema
> column) — the same "small adapter" case as weather's `ncei-climate`. Processing is pure
> config on the S07 subset: `join` (on `iso3,year`) → grouped `derive: cagr(...)` (per
> country) → `score`. Ember/OWID/EIA sources were dropped for v1 (WB indicators are already
> percentages, so `share()` isn't needed here). YAML gotcha: the `join` key must be quoted
> (`"on"`) — bare `on:` parses as boolean `true`.
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md)
(public-sources-only: **free, documented HTTP APIs, no scraping**).
**Depends on:** the full SDK (S02–S05) **and the S07 primitive library** — this dataset is
authored as **config only** on top of the shared adapters/steps/helpers S07 builds. It writes
**no SDK code** and (ideally) **no bespoke adapter**: every source is a built-in
`http_json` / `http_csv` / `sdmx`, every operation a named S07 step/helper.
**Catalog basis:** [`../reports/r01-dataset-catalog-coverage.md`](../reports/r01-dataset-catalog-coverage.md) row 8.
**Template:** [`s06-first-dataset-us-regional-weather.md`](s06-first-dataset-us-regional-weather.md).

**Trigger.** Second production dataset from the product brief — the first that is *100 %
config* (no per-dataset Python), proving the S07 primitive library delivers on
"datasets #2–#30 are config, not code."

---

## Dataset brief

| Field | Value |
|---|---|
| **Topic** | Energy Mix → Renewable Share |
| **Data sources (free APIs)** | World Bank Indicators (no key), Ember Electricity Data (no key), EIA v2 (free token, optional), Our World in Data CSV (no key) |
| **Statistical preprocessing** | Renewable **share / penetration**, **CAGR** (transition speed), composite **transition score** |
| **Value proposition** | Country/region energy-transition intelligence — who is decarbonising, how fast |
| **Target buyers** | Energy investors, ESG funds, utilities, policy analysts |
| **Update regularity** | Daily snapshot (underlying series are annual/monthly; the cron re-cuts the latest) |
| **Size per update** | 3–10 MB |

---

## The whole developer experience

```
datasets/energy-renewable-share/
└── dataset.yaml        # metadata + schema + sources + processing — NO sources.py
```
```bash
datavibes new energy-renewable-share --category energy
datavibes validate energy-renewable-share && datavibes run energy-renewable-share
```
If any bespoke adapter is needed at all it is the **exception**; the goal of this sprint is
**zero** `sources.py`.

### `dataset.yaml`
```yaml
metadata:
  slug: energy-renewable-share
  title: Energy Mix — Renewable Share & Transition Speed
  category: energy
  license: "World Bank CC-BY-4.0; Ember CC-BY-4.0; OWID CC-BY-4.0"
  update_frequency: daily
  attribution: "World Bank Open Data; Ember; Our World in Data"

schema:
  - { name: country,             dtype: str }
  - { name: iso3,                dtype: str }
  - { name: year,                dtype: int }
  - { name: renewable_elec_pct,  dtype: float, unit: "%",  description: "renewable electricity output share" }
  - { name: renewable_fec_pct,   dtype: float, unit: "%",  nullable: true, description: "renewable % of final energy consumption" }
  - { name: fossil_elec_pct,     dtype: float, unit: "%",  nullable: true }
  - { name: renewable_cagr_5y,   dtype: float, unit: "%",  nullable: true, description: "5y CAGR of renewable share" }
  - { name: transition_score,    dtype: float, nullable: true, description: "0–100 composite transition index" }

sources:
  # A — World Bank renewable electricity output (% of total), no key.
  - type: http_json
    url: https://api.worldbank.org/v2/country/all/indicator/EG.ELC.RNEW.ZS
    select: "$[1][*]"
    params: { format: json, per_page: 20000, date: "2000:2024" }
  # B — World Bank renewable energy consumption (% of final energy), no key.
  - type: http_json
    url: https://api.worldbank.org/v2/country/all/indicator/EG.FEC.RNEW.ZS
    select: "$[1][*]"
    params: { format: json, per_page: 20000, date: "2000:2024" }
  # C — Ember yearly electricity generation shares (bulk CSV), no key.
  - type: http_csv
    url: https://ember-energy.org/app/uploads/2024/yearly_full_release_long_format.csv
    select: "$"   # long-format rows filtered in normalize (variable == 'Renewables (% generation)')

processing:
  - normalize                                              # coerce dtypes/units; pivot WB long → wide
  - join:      { on: [iso3, year], how: outer }            # A ⨝ B ⨝ C on country-year
  - derive:    { column: renewable_elec_pct, expr: "share(renewable_generation_gwh, total_generation_gwh)" }
  - derive:    { column: renewable_cagr_5y,  expr: "cagr(renewable_elec_pct, years=5)" }
  - derive:    { column: transition_score,   expr: "score({renewable_elec_pct: 0.5, renewable_cagr_5y: 0.3, renewable_fec_pct: 0.2}, scale=100)" }
  - validate
```

**Every promise → an existing S07 primitive:**

| Dataset promise | S07 step/helper |
|---|---|
| Renewable **share** | `share(part, whole)` / `penetration` |
| Cross-source country-year merge | `join` |
| **Transition speed** | `cagr(col, years)` |
| Composite **transition score** | `score({col: weight, …}, scale)` |

No new SDK primitive is required if S07 shipped `share`, `cagr`, `score`, `join` (all
tabulated in r01). **If S07 is not yet merged, S09 is blocked on it** — do not re-implement
the helpers here.

---

## Data sources (all free, all API/CSV over HTTPS — no scraping)

| Src | Base URL | Auth | Role |
|---|---|---|---|
| A | `https://api.worldbank.org/v2/country/all/indicator/EG.ELC.RNEW.ZS` | **none** | Renewable electricity output % (backbone) |
| B | `https://api.worldbank.org/v2/country/all/indicator/EG.FEC.RNEW.ZS` | **none** | Renewable % of final energy consumption |
| C | Ember yearly full-release CSV | **none** | Generation GWh by fuel → precise shares |
| D | `https://api.eia.gov/v2/…` | **free token** (`EIA_API_KEY`) | *Optional* US state-level detail |

**A — World Bank Indicators (paging via `page`/`pages`)**
```bash
curl -G 'https://api.worldbank.org/v2/country/all/indicator/EG.ELC.RNEW.ZS' \
  --data-urlencode 'format=json' --data-urlencode 'per_page=20000' \
  --data-urlencode 'date=2000:2024'
```
```json
[ {"page":1,"pages":1,"per_page":20000,"total":6650},
  [ {"countryiso3code":"DEU","country":{"value":"Germany"},"date":"2023","value":51.6},
    {"countryiso3code":"FRA","country":{"value":"France"},"date":"2023","value":27.3} ] ]
```
→ built-in `http_json`, `select: "$[1][*]"`; when `pages>1` the built-in follows `page`
(this is exactly the generic pattern `paged_http_json` from S07 handles; per_page=20000
usually collapses to one page).

**C — Ember** long-format CSV (`entity, iso3, year, variable, value, unit`) → `http_csv`;
`normalize` keeps rows where `variable ∈ {Renewables, Total}` and pivots to
`renewable_generation_gwh` / `total_generation_gwh` for the `share()` derive.

**D — EIA v2** (optional, free token) `https://api.eia.gov/v2/electricity/…?api_key=${EIA_API_KEY}`
for US state granularity; the pipeline runs on A+B+C with **no key**.

---

## What this sprint adds to the SDK

**Nothing** — the acceptance criterion. If profiling shows one of `share`/`cagr`/`score`/`join`
is missing from the S07 build, it is a **bug in S07**, fixed there (with its own unit test),
not patched into this dataset.

## Tests
- **End-to-end fixture run**: recorded A/B (World Bank JSON) + C (Ember CSV) bodies → `datavibes
  run energy-renewable-share` produces a golden CSV at the contract path, byte-stable under
  `FixedClock`, columns exactly the declared schema.
- **`join` correctness on real shapes**: a country present in A/B but missing in C (and vice
  versa) yields a row with the expected nullable columns, not a crash.
- **Derive values**: a hand-computed `share` / `cagr(5y)` / `score` for one country matches
  the pipeline output (guards the config wiring, not the helpers — those are S07-tested).
- **No-key path**: fixture run with `EIA_API_KEY` unset still yields a valid snapshot.

## Scope
**IN:** the `energy-renewable-share/` dataset folder (config only) + the fixture tests above.
**OUT:** any SDK/primitive code (that's S07), the EIA state-level expansion (optional
follow-up), and the GitHub Actions cron (shared follow-up for all datasets).

## Definition of done
- [ ] `datavibes validate energy-renewable-share` passes; `run` writes
      `output/energy/energy-renewable-share-<hash>/<ts>.csv`.
- [ ] **Zero** lines of SDK or bespoke-adapter code added — the dataset is pure config.
- [ ] Fixture end-to-end + `join` + derive tests green with **zero** live network.
- [ ] Golden CSV byte-stable under a fixed clock; a valid snapshot is produced from the
      no-key sources (A+B+C) alone.
