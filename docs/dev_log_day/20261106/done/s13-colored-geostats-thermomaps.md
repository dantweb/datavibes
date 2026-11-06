# S13 — `colored-geostats`: thermomap framework + first map dataset (World Population Density)

**Date:** 2026-11-06 · **Type:** Sprint plan · **Status:** ✅ DONE — see [r07](../reports/r07-colored-geostats-implementation.md) (incl. deviations)
**Requirements:** binding — [`_engineering_requirements.md`](../sprints/_engineering_requirements.md).
**Depends on:** S02–S05 (shipped 2026-07-04: registries, `Schema`, `Writer`, `Exporter`,
`FileStore`). It does **not** depend on S07. The World Bank adapter is dataset-local, in the
same way as `ncei-climate` in S06.

**Trigger.** This adds a new product line, **`colored-geostats`**. The product sold is a
**rendered map**: a world map, a single-country map or a region map, colored as a
**thermomap** (choropleth). The underlying numbers ship as a CSV next to it. The first
dataset is **WorldPopulationDensity**.

**Scope note.** S07 declares the primitive set "closed", and R01 states that datavibes emits
tables only. This sprint deliberately opens one new primitive family, **map rendering**. Under
S07's rule that requires a planned sprint, which this is, and must not be added as a
dataset-side hack. After this sprint, map datasets #2…n must again be config-only.

---

## Product definition

| Field | Value |
|---|---|
| **Product line / category** | `colored-geostats` |
| **First dataset (slug)** | `world-population-density` ("WorldPopulationDensity") |
| **Deliverables per run** | `<ts>.svg` (the map) + `<ts>.csv` (the numbers behind every fill) |
| **Output path** | `output/colored-geostats/world-population-density-<hash>/<YYYY-MM-DD-HH-MM>.{svg,csv}` (existing contract; same timestamp stem for both files) |
| **Map scopes supported by the framework** | `world`, `region` (country subset / bbox), `country` (admin-1 subdivisions) |
| **Scope shipped in this sprint** | `world` only (region/country are tested with fixtures; real datasets come later) |
| **Data source (free, no key)** | World Bank WDI API: `EN.POP.DNST` (people per km² of land), `SP.POP.TOTL.FE.ZS` (female % of population) |
| **Geometry (public domain)** | Natural Earth 1:110m Admin-0 countries, pinned version, vendored with a provenance manifest |
| **Update frequency** | monthly (WDI values are annual; the monthly run picks up revisions) |
| **New runtime dependencies** | **none**: SVG is built with the stdlib (`colorsys`, string building) |

---

## The two color scales (the core of the product)

All color math is **pure**: rows in, hex colors + legend out. There is no I/O and no clock
read, and each scale is unit-tested.

### Shared: density normalization → `[floor, ceil]`

Raw densities span about five orders of magnitude (Greenland ≈ 0.14/km², Bangladesh ≈
1,300/km², city-states ≈ 20,000/km²). A linear min–max would leave almost every country at
the floor. Default transform:

```
t(d)        = log10(d)                                    # method: log  (default)  | linear
norm(d)     = (t(d) - t_min) / (t_max - t_min)           # over the rows being drawn
scaled(d)   = floor + (ceil - floor) * norm(d)           # floor = 0.1, ceil = 1.0
```

- `d <= 0`, null or NaN → **no data** (it is not clamped). It is drawn in the no-data grey and
  excluded from `t_min/t_max`.
- If every value is equal (`t_max == t_min`), every row gets `(floor + ceil) / 2`. This is
  documented and tested.
- **Home:** one pure helper `scale_to_range(values, method, floor, ceil)` in
  `datavibes/processing/functions.py`. The CSV `derive` step and both color scales call it,
  so the CSV value and the map color can never drift apart (DRY).

### Scale A — `sex-ratio-bivariate` (default for the first dataset)

| Input | Rule |
|---|---|
| **Hue** from `male_share_pct` | `> 50 + tolerance` → **blue** (more men than women) · `< 50 − tolerance` → **red** (more women than men) · within tolerance → neutral grey. `tolerance` defaults to `0.05` pp. |
| **Saturation** from `density_per_km2` | `scaled(d)` with `floor = 0.1` (low density) and `ceil = 1.0` (high density) |
| **Lightness** | fixed, `0.5` by default (configurable) |

Color = `HSL(hue, saturation, lightness)` → hex, using `colorsys.hls_to_rgb`. Each channel
is rounded half-up so the hex string is deterministic. Defaults: blue hue `212°`, red hue
`0°`. At `s = 1.0` this gives fully saturated blue/red. At `s = 0.1` it gives an almost-grey
tint of the same hue.

**Legend:** two horizontal gradient bars, "More men" (blue) and "More women" (red). Each
runs from saturation 0.1 to 1.0, with ticks labeled in **real units** (people/km²), obtained
by inverting the transform at 0 / 0.5 / 1. There is also a "No data" swatch and a "≈ equal"
swatch.

### Scale B — `spectral-density` (the requested option)

This scale uses only density. Sex ratio is ignored. Color stops are placed on the
normalized axis `norm ∈ [0, 1]`, with **green fixed at the set average**:

| Stop | Position on `norm` | Default color |
|---|---|---|
| dark blue (lowest) | `0` | `#08306b` |
| sky blue | `center / 2` | `#4fc3f7` |
| **green (average)** | `center` = mean of `norm` over the drawn set | `#2e9e44` |
| yellow | `center + (1 − center) · 1/3` | `#ffd400` |
| orange | `center + (1 − center) · 2/3` | `#ff8c00` |
| red (highest) | `1` | `#d7191c` |

- Colors are interpolated linearly in sRGB between neighboring stops, then rounded to hex.
- `center: mean` is the default, as specified. `center: median` is accepted because log
  densities are skewed, and the median often reads better.
- The mean is taken **after** the log transform, so the average sits at roughly the
  geometric mean density. A raw arithmetic mean would be dragged up by city-states and
  would turn almost the whole map blue.
- The stop colors can be overridden in config. The positions are fixed, because they are
  the definition of this scale.
- **Legend:** one gradient bar with ticks at min, average and max in real units.

> ⚠️ A rainbow scale is not color-vision-deficiency safe. It ships because it was asked for,
> but `sex-ratio-bivariate` stays the default. A CVD-safe sequential scale can be added
> later as one more registry entry, with no SDK change.

---

## Architecture: what is added (and where)

```
datavibes/
├── maps/                                   # NEW package — the map framework
│   ├── __init__.py
│   ├── color_scales.py                     # ColorScale ABC + sex-ratio-bivariate + spectral-density
│   ├── color_math.py                       # hsl→hex, hex lerp, stop interpolation (pure)
│   ├── geometry.py                         # load vendored GeoJSON via manifest; filter by scope; bbox
│   ├── projection.py                       # equirectangular, equal-earth (pure lon/lat → x/y)
│   ├── svg.py                              # rings → path data; legend → SVG fragments (pure)
│   └── geometry/
│       ├── manifest.yaml                   # name, file, source_url, version, sha256, license, key property, level
│       └── ne_110m_admin_0_countries.geojson   # pinned Natural Earth, coords quantized to 3 dp
├── export/writers.py                       # + SvgMapWriter registered as "svg-map"
├── registry.py                             # + COLOR_SCALE_REGISTRY / register_color_scale / resolve_color_scale
│                                           #   resolve_writer(name, options={}) → cls(**options)
├── config/models.py                        # + DatasetConfig.outputs (list of writer specs; default [defaults.format])
├── export/exporter.py                      # + export_outputs(config, rows) → list[Path], one shared timestamp
├── sdk.py / cli.py                         # + run_outputs(slug); `run` prints every written path
└── processing/functions.py                 # + scale_to_range, complement, sex_majority (pure helpers)

datasets/
├── world-population-density/               # first dataset (bivariate scale)
│   ├── dataset.yaml
│   └── sources.py                          # `worldbank-latest` adapter (~40 lines)
└── world-population-density-heat/          # the spectral option, proved config-only
    └── dataset.yaml
```

### New narrow interface (ISP)

```python
class ColorScale(ABC):
    """Maps rows to fill colors. Pure: rows in, Painting out."""

    @abstractmethod
    def paint(self, rows: list[dict]) -> "Painting":
        """Return per-row fills (hex or None = no data), aligned to ``rows``, plus the legend."""

@dataclass(frozen=True)
class Painting:
    fills: list[str | None]
    legend: "Legend"          # gradient bars + ticks in real units + no-data swatch
```

Scales register with `@register_color_scale("sex-ratio-bivariate")` and
`@register_color_scale("spectral-density")`. Adding a scale is a new class plus a decorator.
The writer never changes (OCP).

### Writer options (minimal SDK change)

Today `resolve_writer(name)` calls `cls()`, so writers cannot take options. Change it to
`resolve_writer(name, options=None) → cls(**(options or {}))`, matching how sources and steps
are already resolved. The `csv`/`json`/`parquet` writers are unaffected, and existing tests
stay green.

### Multiple outputs per run

`DatasetConfig` gains an optional `outputs:` list. If it is absent, the behavior is exactly
what it is today: one output in `defaults.format`. `Exporter.export_outputs` reads the clock
**once**, so `<ts>.csv` and `<ts>.svg` share a stem. `run()` keeps its current signature and
returns the first output's path. The new `run_outputs()` returns all paths. An explicit
`--format` on the CLI still forces a single output.

### `svg-map` writer (SRP: it only renders)

`SvgMapWriter.write(rows, schema, dest)`:
1. Loads the geometry named in options from the manifest. It is vendored, so the writer
   needs **no network**.
2. Filters features by `scope` and computes the extent.
3. Joins rows to features on `key_column` ↔ the geometry `key_property`, with
   `key_aliases` for known code mismatches. Rows without geometry and geometry without rows
   are collected into a **join report**. Unmatched features are drawn in the no-data fill.
4. Calls `resolve_color_scale(spec).paint(matched_rows)`.
5. Projects, then emits the SVG:
   - one `<path id="<ISO3>">` per feature with `fill-rule="evenodd"` (holes), a white
     0.3 px border, and a `<title>` tooltip giving the name and every `label_columns` value;
   - the legend, title, and the source attribution + data year.
6. Writes the join report next to the map as `<ts>.join.json`. Unmatched keys are visible
   rather than silent.

**Determinism (Req 7):** features are sorted by key, coordinates are rounded to 0.1 px on a
fixed `1000 × 500` viewBox (world), there is no generation timestamp in the SVG, attribute
order is fixed, and the newline is `\n`. Same rows ⇒ identical bytes.

### Scopes

| `scope` | Options | Behaviour |
|---|---|---|
| `world` | — | all features; default projection `equal-earth` (equal-area, which is correct for density choropleths) |
| `region` | `iso3: [...]` or `continent: Europe`, optional `clip_bbox: [lon_min, lat_min, lon_max, lat_max]` | filter features, fit the viewBox to the bbox. `clip_bbox` exists because Natural Earth's France includes French Guiana, which would otherwise stretch a Europe map |
| `country` | `country: DEU`, geometry level `admin1` | features are the subdivisions of one country; default projection `equirectangular` with a `cos(lat₀)` aspect correction |

Projections are two pure functions in a plain dict. No registry, because two entries don't
justify one.

---

## First dataset — `datasets/world-population-density/dataset.yaml`

```yaml
metadata:
  slug: world-population-density
  title: World Population Density — Sex-Ratio Thermomap
  category: colored-geostats
  license: "CC BY 4.0 (World Bank WDI); map geometry public domain (Natural Earth)"
  update_frequency: monthly
  attribution: "World Bank World Development Indicators; Natural Earth"

schema:
  - { name: iso3,               dtype: str }
  - { name: country,            dtype: str }
  - { name: density_per_km2,    dtype: float, unit: "people/km2" }
  - { name: density_year,       dtype: int }
  - { name: female_share_pct,   dtype: float, unit: "%" }
  - { name: male_share_pct,     dtype: float, unit: "%" }
  - { name: sex_year,           dtype: int }
  - { name: majority,           dtype: str, description: "male | female | equal" }
  - { name: density_saturation, dtype: float, nullable: true, description: "log-normalised density in [0.1, 1.0] — the map saturation" }

sources:
  - type: worldbank-latest          # dataset-local adapter (sources.py)
    indicators:
      EN.POP.DNST:       { value: density_per_km2,  year: density_year }
      SP.POP.TOTL.FE.ZS: { value: female_share_pct, year: sex_year }
    most_recent_non_empty: true         # WB `mrnev=1` → latest available year per country
    exclude_aggregates: true            # drop "World", "Euro area", income groups, ...

processing:
  - normalize
  - derive:   { column: male_share_pct,     expr: "complement(female_share_pct, total=100)" }
  - derive:   { column: majority,           expr: "sex_majority(male_share_pct, tolerance=0.05)" }
  - derive:   { column: density_saturation, expr: "scale_to_range(density_per_km2, method=log, floor=0.1, ceil=1.0)" }
  - validate

outputs:
  - csv
  - svg-map:
      geometry: natural-earth-admin0-110m
      scope: world
      projection: equal-earth
      key_column: iso3
      key_aliases: { XKX: KOS, SSD: SDS }       # WB code → Natural Earth ADM0_A3 (verify the full list during the sprint)
      label_columns: [country, density_per_km2, male_share_pct, density_year]
      title: "Population density & sex ratio by country"
      color_scale:
        type: sex-ratio-bivariate
        ratio_column: male_share_pct
        value_column: density_per_km2
        normalize: log
        saturation_range: [0.1, 1.0]
        tie_tolerance_pct: 0.05
```

### The spectral option — `datasets/world-population-density-heat/dataset.yaml`

This uses the same metadata/sources/processing pattern with a different slug and title. Only
the `color_scale` block differs:

```yaml
      color_scale:
        type: spectral-density
        value_column: density_per_km2
        normalize: log
        center: mean            # green = average of the set
```

Sources and processing are duplicated across the two folders. That is accepted because it
is config only. Shared config includes (`extends:`) are **not** built here; they wait until a
third map dataset needs them.

### `worldbank-latest` adapter (dataset-local)

- `GET https://api.worldbank.org/v2/country/all/indicator/<CODE>?format=json&mrnev=1&per_page=1000&page=N`
  for each indicator. It follows `pages` from the response's element `[0]`.
- With `exclude_aggregates`, it fetches `GET /v2/country?format=json&per_page=400` once and
  drops ids whose `region.value == "Aggregates"`.
- It merges the indicators by `countryiso3code` into one record per country, mapped
  per indicator to `{value, year}`. Null values are dropped. A country missing one
  indicator is kept with a null, and `validate` decides whether that is allowed.
- Uses the SDK-injected HTTP client (DI). A network failure or an empty response yields an empty result and never crashes (LSP).
- Once S07's `sdmx`/`paged_http_json` + `join` land, this adapter can be replaced with
  config. That swap is noted, not done here.

---

## TDD build order (each phase green before the next)

1. **Color math + normalization (pure).** `scale_to_range`, `complement`, `sex_majority`,
   `hsl_to_hex`, `lerp_hex`, stop interpolation.
2. **Color scales.** The `ColorScale` ABC, its registry, `sex-ratio-bivariate`,
   `spectral-density`, and the `Legend` value object.
3. **Geometry + projection.** Manifest loader with sha256 verification, scope filters,
   bbox, `equirectangular`, `equal-earth`.
4. **`svg-map` writer.** Writer options, `outputs:` list, `export_outputs`,
   `run_outputs`, CLI printing.
5. **Dataset.** `worldbank-latest` adapter, `world-population-density` config, end-to-end
   golden test.
6. **Option proof.** The `world-population-density-heat` config, with an end-to-end golden
   test and **no SDK edit**.
7. **Live smoke** (manual, outside CI): one real run of each dataset. Record row count,
   join-report size and file sizes in a report under `../reports/`.

---

## Tests

**Pure (no fixtures beyond literals)**
- `scale_to_range` with log: `[1, 10, 100]` → `[0.1, 0.55, 1.0]`. Linear: known values.
  All-equal → all `0.55`. `0`/negative/None → None and excluded from min/max.
- `sex_majority`: `50.06` → male, `49.94` → female, `50.04` → equal (tolerance 0.05).
  The boundary is exact at ±tolerance and documented.
- `hsl_to_hex`: `(212°, 1.0, 0.5)` and `(0°, 1.0, 0.5)` match the published hex values.
  `s = 0.1` gives a near-grey of the same hue.
- `sex-ratio-bivariate`: min density → saturation 0.1 and max → 1.0. Saturation is monotonic
  in density. The hue sign follows the majority. Ties → neutral. Missing ratio or density →
  `None` (no data).
- `spectral-density`: min → `#08306b`, max → `#d7191c`, a row exactly at the mean → `#2e9e44`.
  The stop order is preserved, and `center: median` moves the green anchor. A single row and
  all-equal rows are guarded.
- Legend tick labels invert the transform (the `0.5` tick on a log scale over `[1, 100]`
  reads `10`).
- Projections: `(0, 0) → (0, 0)` for both. The equal-earth x at `(180°, 0°)` matches the
  reference value from the formula's paper. Both are symmetric under lon/lat sign flips.

**Writer (fixture geometry: three squares + one square with a hole)**
- A golden SVG matches byte for byte. Features are sorted by key. Fills are correct. The hole
  is rendered via `evenodd`. The legend, title and attribution are present. The SVG contains
  no timestamp.
- An unmatched data row and an unmatched feature both appear in the join report, and the
  feature gets the no-data fill.
- `key_aliases` remaps before the join.
- `region` scope with `iso3` and with `clip_bbox` changes the viewBox as expected. `country`
  scope runs on fixture admin-1 squares.
- A geometry file whose sha256 doesn't match its manifest entry raises a `DatavibesError`
  that names the file.

**Adapter (network mocked with recorded WB bodies)**
- Pagination walks every page. Aggregates are excluded. Two indicators are merged by ISO3
  with their own years. A null value is dropped. An HTTP error yields an empty result.

**End to end (`FixedClock`, `static` stand-in for WB)**
- `run_outputs("world-population-density")` writes `<ts>.csv`, `<ts>.svg` and
  `<ts>.join.json` at the contract path. All match their goldens and are byte-stable across
  two runs.
- The same holds for `world-population-density-heat`. Its CSV is identical to the
  bivariate dataset's CSV and only the SVG differs, which proves the scale is purely a
  presentation option.
- Existing single-output datasets (`us-regional-weather`) are unchanged: same paths, same
  bytes.

---

## Scope

**In:** the `datavibes/maps/` framework (two color scales, geometry manifest, two
projections, SVG renderer with legend + join report); writer options; the `outputs:` list;
three pure helpers; the vendored Natural Earth 110m admin-0 geometry; the
`world-population-density` dataset (bivariate) and `world-population-density-heat`
(spectral); README section "Map datasets".

**Out:** PNG/PDF export (follow-up: an optional `png-map` writer via the `cairosvg` extra);
real country/region map datasets and their admin-1 geometry (the 10m admin-1 file is ≈ 40 MB,
which needs a fetch-and-cache strategy and a decision of its own); more projections;
CVD-safe scales; an interactive/HTML map; animated time series; shared-config `extends:`;
cron/CI wiring (still in the backlog).

---

## SOLID mapping

- **SRP:** the adapter fetches, the `derive` helpers compute numbers, `ColorScale` only maps
  numbers to colors, and `SvgMapWriter` only renders. Normalization lives in one helper.
- **OCP:** new scales register into a fourth registry. New map datasets are folders. New
  geometries are manifest entries.
- **LSP:** every `ColorScale` honours `paint(rows) -> Painting`, and `svg-map` honours
  `Writer.write`. Empty rows produce a valid all-no-data map, never a crash.
- **ISP:** `ColorScale` has one method. The `Writer` interface is unchanged.
- **DIP/DI:** the writer receives its scale spec and geometry name through options and
  resolves them through the registry and manifest. The HTTP client is injected into the
  adapter. Nothing in `maps/` reads the network or the clock.
- **No overengineering:** two scales, two projections, one geometry file, no new
  dependencies, no config inheritance.

---

## Definition of done

- [ ] `pip install -e .` from a cold clone, then `make test` is green. The suite makes
      **zero** live network calls, and every new module has tests written first.
- [ ] `datavibes run world-population-density` (live) writes `.csv` + `.svg` +
      `.join.json` under `output/colored-geostats/world-population-density-<hash>/`. The SVG
      opens in a browser: blue/red countries with saturation tracking density, plus a legend.
- [ ] `datavibes run world-population-density-heat` writes the spectral map. Green sits on
      average-density countries, dark blue on the sparsest and red on the densest.
- [ ] The join report for the live world run has been reviewed. The remaining unmatched
      entries are only territories that genuinely lack WB data or a 110m geometry, and they
      are listed in the run report.
- [ ] `us-regional-weather` output is byte-identical to before this sprint.
- [ ] The README documents the map datasets: `outputs:`, `svg-map` options, both scales, and
      how to add a scale.
- [ ] Natural Earth version + sha256 are recorded in `manifest.yaml`, and the attribution
      appears in every SVG.

---

## Open questions / risks

1. **Cross-repo: the VBWD `dataset` plugin** ([[project_s110_datasets_plugin]]) has only
   served `.csv` so far. Can it serve and preview `.svg` (+ `.json`) files from the same
   snapshot folder, and which one is the "primary" file for a buyer? This must be confirmed
   before the product goes live. It does not block this sprint.
2. **Normalization domain for region/country maps:** the default normalizes over the
   features drawn, so each map uses the full saturation range. The alternative is a global
   domain, which makes colors comparable across maps. The default stays per-map unless
   product says otherwise.
3. **Disputed and missing territories** (Kosovo, Western Sahara, Taiwan, N. Cyprus,
   Somaliland, …): Natural Earth draws de facto boundaries, and WB has no data for some of
   these. They render as "No data". The SVG footer should carry a short boundary
   disclaimer.
4. **Micro-states** (Monaco, Singapore, Bahrain, …) are absent from the 110m geometry.
   Their rows are still in the CSV, and the join report lists them. Rendering them would
   need either the 50m geometry or point markers. That is deferred.
5. **Data recency differs per indicator** (`density_year` ≠ `sex_year` for some countries).
   Both years are kept in the CSV. The SVG states the most common year and "latest
   available" in the footer.
