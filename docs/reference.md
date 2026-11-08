# Reference: every building block

Everything a `dataset.yaml` can name. All of them are registered at import time;
`datavibes validate <slug>` names the known ones whenever you mistype one.
Tutorial: [creating-datasets.md](creating-datasets.md) · Operations:
[managing-datasets.md](managing-datasets.md) · Report charts: [charts.md](charts.md).

**Conventions:** _italic_ options are required. Every string option accepts
`${VAR}` / `${VAR:-default}`. `select` uses JSONPath-lite: `$`, `$.a.b`, `$.a[*]`,
`$[*]`. A miss yields no records, never an error.

---

## Sources (`sources:` → `type:`)

| Type | Options | Use it for |
|---|---|---|
| `static` | `records` (list) or `records_file` | Fixtures, scaffolds, hand-curated lists |
| `http_json` | _`url`_, `select` = `$`, `params`, `headers` | One JSON document |
| `http_csv` | _`url`_, `delimiter` = `,`, `encoding`, `params`, `headers` | One CSV document (header row → keys) |
| `paged_http_json` | _`url`_, `select` = `$[*]`, `paging` = `page`\|`offset`\|`cursor`, `fields`, `page_param`, `page_size_param`, `page_size` = 100, `start_page`, `offset_param`, `cursor_select`, `max_pages` = 10, `token_env`, `auth_scheme` = `Bearer`, `delay_seconds` | Paged REST APIs; stops at the first empty/short page or `max_pages` |
| `multi_http_json` | _`url`_ with `{key}` placeholders, `items` (list of dicts), `fields` (`column: dotted.path`), `select`, `carry`, `params`, `headers`, `token_env`, `auth_scheme`, `delay_seconds` | "One request per entity" (a GitHub repo per project). A failed item is skipped. |
| `columnar_http_json` | _`url`_, _`index`_, `fields`, `items`, `index_column`, `select`, `carry`, `params`, `headers`, `token_env`, `auth_scheme`, `delay_seconds`, `max_rows` | Time series returned as parallel arrays (Open-Meteo, energy-charts) |
| `jsonstat` | _`url`_, _`value_column`_, `dimensions` (`dim: column` for codes), `label_columns` (`dim: column` for labels), `params`, `headers` | JSON-stat 2.0 cubes (Eurostat, e-Stat) |
| `worldbank-indicator` | `indicators` (`CODE: column`), `date_range` = `2000:2024`, `per_page`, `delay_seconds` = 1.0 | World Bank panels: one row per country-year **per indicator**, then `join` |
| `worldbank-latest` | _`indicators`_ (`CODE: {value: column, year: column}`), `most_recent_non_empty` = true, `exclude_aggregates` = true, `base_url`, `per_page`, `max_pages` | The **latest** value per country, indicators merged per ISO3; regional/income aggregates dropped |
| `faostat-prices` | _`item`_ (FAO item name), _`areas`_ (`ISO3: {label, names: [FAO area], archive_names: [FAO area]}`), `value_column` = `price_slc_per_tonne`, `basis_column` = `price_basis`, `archive_rescale` (`ISO3: {before \| from, factor, reason}`), `archive_exclude` (`ISO3: reason` drops the whole archive, `ISO3: {before, reason}` only its early years), `index_exclude` (`ISO3: reason`: no index extension), `current_url`, `archive_url` (null = current only), `timeout_seconds` = 120 | FAOSTAT producer prices for one item, 1966→today, in today's currency. Archive (1966–1990) is converted with FAO's own SLC÷LCU ratio; gaps are filled from FAO's price index; every row has a `price_basis`: `observed` · `archive-rebased` · `index-extended` |
| `bis-series` | _`dataflow`_ (`WS_SPP` indices, `WS_DPP` detailed incl. per-m² levels, …), _`series`_ (`ISO3: {REF_AREA: XX, <DIMENSION>: code, …, multiplier}`), _`value_column`_, `filters` (shared dimension codes), `basis_column` + `basis` = `observed`, `url`, `timeout_seconds` = 120 | BIS statistics bulk files; dimension cells are matched on their code; quarterly/monthly values averaged per year. Quote `REF_AREA: "NO"` (bare `NO` is YAML false) |
| `worldbank-pinksheet` | _`commodities`_ (`Sheet name: column`, e.g. `Silver: silver_usd_per_troy_oz`), `url` (pin a file), `page_url`, `timeout_seconds` = 120 | World Bank commodity prices (Pink Sheet), annual nominal USD, 1960→. Follows the current file link on the commodity-markets page. Rows have no country: broadcast them with `lookup: {from_source: worldbank-pinksheet, on: year, …}`. Needs `openpyxl` |
| `bls-series` | _`series`_ (`ISO3: BLS series id`), _`value_column`_, `start_year` = 1953, `end_year` (default: this year), `url`, `timeout_seconds` = 60, `retries` = 3 | US BLS API v1, keyless: POSTs 10-year windows, averages M01–M12 per year. Keyless quota is 25 requests/day |
| `ilostat` | _`indicator`_ (e.g. `EAR_EMTA_SEX_EDU_NB_A`), _`ref_areas`_ (ISO3 list), _`value_column`_, `filters` (`sex` sent to the API; `classif1`, … applied locally), `source_column`, `fill_from_other_surveys` = false, `exclude_before` (`ISO3: {year, reason}`), `timeout_seconds` = 120 | ILOSTAT indicators as country-year rows. Keeps each country on its longest-running survey so survey switches don't create jumps |
| `sparql` | _`query`_, `endpoint` = Wikidata, `strip_uri_prefix` = false, `timeout_seconds` = 90 | Any SPARQL 1.1 endpoint; numeric literals → float; every `SELECT` variable becomes a column |

Dataset-local adapters (`datasets/<slug>/sources.py`): `ncei-climate`
(us-regional-weather), `cloud-price-list` (hosting-cloud-pricing), `iea-ev`
(vehicle-production-ev-share).

Each record also carries `_source: "<type>#<index>"`. `lookup` uses it, and
`normalize` drops it.

---

## Processing steps (`processing:`)

A step is written as a bare name (`- normalize`) or a one-key mapping
(`- derive: { … }`). Steps run in order.

| Step | Options | Effect |
|---|---|---|
| `rename` | _`columns`_ (`old: new`) | Rename raw keys. Put it **before** `normalize`. |
| `lookup` | _`from_source`_ (source type), _`on`_ (key column), _`columns`_ (`lookup_col: target_col`) | One-to-many enrichment: copies columns from that source's rows onto every other row with the same key, then drops the lookup rows. Put it before `normalize`. |
| `normalize` | — | Coerce schema columns to their dtypes; **drop every non-schema key** |
| `dedupe` | _`keys`_, `keep` = `first`\|`last` | Remove duplicate rows |
| `join` | _`on`_ (list; quote it as `"on"`), `how` = `outer` | Coalesce rows sharing the key into **one** row (columns unioned, later non-null wins) |
| `filter` | exactly one of `when` (condition) / `all` (list) / `any` (list); `reason` | Keep matching rows. `reason` labels the dropped rows in map legends and `join.json`. |
| `flag` | _`column`_, `when` / `all` / `any` | Boolean column from conditions |
| `classify` | _`column`_, _`value`_, _`bins`_ (`[{label, min?, max?}]`, first match wins, no bounds = catch-all), `default` | Bucket a number into labels |
| `derive` | _`column`_, _`expr`_ (`helper(col, col2, key=literal)`), `by` (group columns), `params` (extra keywords, e.g. a YAML anchor) | Add or overwrite a column with a helper (below) |
| `aggregate` | _`by`_, _`metrics`_ (`column: mean\|median\|min\|max\|sum\|count`) | One row per group |
| `score` | _`column`_, _`weights`_ (`column: weight`), `scale` = 1 | Weighted composite of min-max-normalised inputs |
| `forecast` | _`column`_, _`value`_, `by`, `horizon` = 1, `window` = 5, `method` = `linear` | Least-squares projection per group (sort by time first) |
| `age_days` | _`column`_, _`value`_ (ISO timestamp column) | Days between the timestamp and the run instant |
| `sort` | _`by`_ | Stable sort, nulls last. Gives deterministic output and time order for windowed helpers. |
| `map` | _`column`_, _`key`_, _`mapping`_ (`key value: new value`) | Set a column from a fixed table (ISO3 → display name); rows whose key isn't listed keep their value |
| `chain_index` | _`column`_ (level), _`index`_ (one column, or a list best-first), `by`, `time` = `year`, `basis_column`, `chained_label` = `index-chained` (or one per index) | Fill a level's missing years per group. One index: level(anchor) × index(year) ÷ index(anchor), nearest anchor. A list: grow year by year, each link using the first index that covers both years (splices a short specific index with a long general one) |
| `validate` | —  | Fail the run if any row breaks the schema. **Put it last.** |

**Condition syntax** (`filter`, `flag`): `{ column: x, <operator>: value, … }`.
Every listed operator must hold. Operators: `gt`, `gte`, `lt`, `lte`, `eq`, `ne`,
`in`, `not_in`, `is_null: true`, `not_null: true`.

---

## Derive helpers (`derive: { expr: "helper(…)" }`)

Positional arguments are **column names**; `key=value` arguments are literals.
Every helper returns one value per row and turns invalid input into `None`.
With `by:`, the helper runs separately within each group.

| Helper | Signature | Result |
|---|---|---|
| `ratio` | `ratio(a, b)` | a ÷ b |
| `add` / `subtract` | `add(a, b)` | a ± b |
| `share` / `penetration` | `share(part, whole)` | part ÷ whole × 100 |
| `share_of_total` | `share_of_total(x)` | x as % of the column total |
| `complement` | `complement(x, total=100)` | total − x |
| `pct_change` | `pct_change(x)` | Fractional change vs. the previous row |
| `yoy` | `yoy(x, periods=1)` | % change vs. `periods` rows back |
| `cagr` | `cagr(x, years=1)` | Compound annual growth % over a trailing lag |
| `rolling_avg` | `rolling_avg(x, window=N)` | Trailing mean |
| `volatility` | `volatility(x, window=N)` | Trailing sample std-dev |
| `rolling_corr` | `rolling_corr(a, b, window=N)` | Trailing Pearson correlation |
| `corr` | `corr(a, b)` | Whole-series correlation, broadcast |
| `anomaly` | `anomaly(x, baseline=…)` | x − baseline (numeric) or x − mean |
| `zscore` | `zscore(x)` | (x − mean) ÷ std-dev |
| `minmax_normalize` | `minmax_normalize(x, invert=false)` | Scale to [0, 1] |
| `scale_to_range` | `scale_to_range(x, method=log\|linear, floor=0.1, ceil=1.0)` | Normalise to [floor, ceil]; log ignores ≤ 0. The map scales use the same function. |
| `gini` / `hhi` | `gini(x)` | Inequality / concentration index, broadcast |
| `seasonal_index` | `seasonal_index(x, period=N)` | Phase mean ÷ grand mean |
| `linear_forecast` | `linear_forecast(x, horizon=1, window=5)` | Trailing least-squares projection |
| `at_least` | `at_least(x, threshold=…)` | True if x ≥ threshold |
| `sex_majority` | `sex_majority(male_pct, tolerance=0.05)` | `male` / `female` / `equal` |
| `null_outside` | `null_outside(x, low=…, high=…)` | x if within [low, high], else None |
| `round_to` | `round_to(x, digits=2)` | Rounded |
| `product` | `product(a, b)` | a × b (a USD amount × LCU per USD) |
| `scale` | `scale(x, factor=1, divisor=1)` | x × factor ÷ divisor: unit conversions (per tonne → per egg, per year → per month) |

---

## Outputs (`outputs:`)

Without `outputs:`, a dataset writes one file in `config.yaml defaults.format` (csv).
Each writer may appear only once per dataset.

| Writer | Options |
|---|---|
| `csv` | — (schema column order; empty cell for null) |
| `json` | — (array of objects, schema key order) |
| `parquet` | — (needs `pip install 'datavibes[parquet]'`) |
| `xlsx` | `pivots`, `title`, `attribution`, `license`, `notes`: see below (needs `pip install 'datavibes[xlsx]'`) |
| `svg-small-multiples` | see below |
| `svg-map` | see below |
| `svg-dot-map` | everything `svg-map` takes except `key_column`, plus the dot options below |

### The same writer twice: `suffix`

Any output takes `suffix: <name>` (lowercase, digits, dashes). The file becomes
`<timestamp>.<suffix>.<extension>`, so one dataset can write two charts with the
same writer, e.g. `<ts>.svg` and `<ts>.graduates.svg`.

### `xlsx`: Excel workbook

Sheets: `data` (every schema column), one sheet per pivot, `About` (title, attribution, licence, notes, column dictionary).

| Pivot key | Meaning |
|---|---|
| _`sheet`_, _`index`_, _`columns`_, _`values`_ | Sheet name; row key (e.g. `year`); one column per distinct value (e.g. `country`); cell value |
| `order` | Column order (default: sorted) |
| `index_range` | `[low, high]`: a row for every integer key, empty where there is no data (honest gaps) |
| `chart` | `{title, x_title, y_title, x_range: [low, high], log_y, anchor}`: a native Excel scatter-with-lines chart, one line per column |

### `svg-small-multiples`: one time-series panel per entity

For more than about 8 series: each panel draws its entity as the one coloured line, every other entity in grey, on shared axes. Light/dark aware; native `<title>` tooltips; the latest value is labelled.

| Option | Default | Meaning |
|---|---|---|
| _`x`_, _`y`_, _`facet`_ | | Time column, value column, entity column |
| `facet_order` | sorted | Panel order |
| `x_range` | data range | `[low, high]`: pin the axis (gaps stay visible) |
| `y_scale` | `linear` | `linear` · `log` |
| `basis_column` + `estimated` | | Segments touching a row whose basis is in `estimated` are dashed |
| `columns`, `panel_width`, `panel_height` | 4, 280, 170 | Grid layout |
| `reference_y`, `reference_label` | | A second column drawn as a thin dark line in every panel (e.g. the whole-population value behind a sub-group) |
| `show_empty`, `empty_note` | false, `no data` | Draw a panel, with the note, for `facet_order` entries that have no data |
| `title`, `subtitle`, `y_label`, `unit`, `footer` | | Text; `unit` goes into tooltips |

### `svg-map`: country / region choropleth

| Option | Default | Meaning |
|---|---|---|
| _`geometry`_ | — | Manifest name; shipped: `natural-earth-admin0-110m` (177 countries, key `ADM0_A3`) |
| _`color_scale`_ | — | `{type: …, …}`, see colour scales |
| _`key_column`_ | — | Row column matched against the geometry key |
| `key_aliases` | `{}` | Data code → geometry code (World Bank → NE: `SSD: SDS`, `PSE: PSX`, `XKX: KOS`) |
| `scope` | `world` | `world` · `region` (+ `region: {iso3: […]}` or `{continent: …}`) · `country` (+ `country: ISO3`, admin-1 geometry) |
| `clip_bbox` | — | `[lon_min, lat_min, lon_max, lat_max]`: crop the canvas |
| `exclude` | `[]` | Geometry keys not to draw (e.g. `ATA`) |
| `projection` | `equal-earth` (world) / `equirectangular` | `equal-earth` · `equirectangular` |
| `label_columns` | `[]` | Tooltip contents |
| `item_label` | `areas` | Noun used in the legend's Coverage block ("countries") |
| `title`, `footer`, `disclaimer` | | Text above and below the map |
| `width` | 1000 | Canvas width in px (height follows) |
| `background`, `no_data_color`, `border_color`, `border_width` | `#ffffff`, `#d9d9d9`, `#ffffff`, 0.3 | Styling |
| `geometry_manifest` | packaged | Path to another manifest (custom geometry) |

Writes `<ts>.svg` and `<ts>.join.json` (`features_without_rows`,
`features_with_missing_values`, `rows_not_drawn`, `duplicate_row_keys`, `excluded`).

### `svg-dot-map`: one dot per row

| Option | Default | Meaning |
|---|---|---|
| _`latitude_column`_, _`longitude_column`_ | — | Dot position; rows without coordinates are counted, not drawn |
| _`size_column`_ | — | Dot **area** ∝ value (radius ∝ √value); largest drawn first |
| `min_radius` / `max_radius` | 1.0 / 12.0 | px |
| `size_legend` | `[100000, 1000000, 10000000]` | Reference circles |
| `size_label`, `name_column` | | Legend text; tooltip heading |
| `basemap_color` | `#e3e6ea` | Countries are drawn as a neutral basemap |
| `dot_opacity`, `dot_stroke` | 0.85, `#ffffff` | Use a dark stroke when dots can be near-white |
| `item_label` | `points` | "Cities shown: N of M" |

`join.json`: `drawn_points`, `points_without_color`, `rows_without_coordinates`, `excluded`.

### Colour scales (`color_scale: { type: … }`)

| Type | Options | Colouring |
|---|---|---|
| `sex-ratio-bivariate` | _`ratio_column`_ (male share %), _`value_column`_, `normalize` = log, `saturation_range` = [0.1, 1.0], `tie_tolerance_pct` = 0.05, `male_hue` = 212, `female_hue` = 0, `lightness` = 0.5, `equal_color`, `value_label`, `ratio_label` | Blue = more men, red = more women, grey = ≈ equal. White → full colour by the normalised value. |
| `spectral-density` | _`value_column`_, `normalize` = log, `center` = mean\|median, `saturate_above` (value → red), `colors` (6 hex), `value_label` | Dark blue → sky blue → **green = average** → yellow → orange → red |

New scale: a class implementing `ColorScale.paint(rows) -> Painting`, registered
with `@register_color_scale("name")`.

### Geometry

`datavibes/maps/geometry/manifest.yaml` lists every file with `source_url`,
`version`, `license`, `key_property`, `name_property`, `level` and `sha256`. The
file is verified on load. `make geometry` re-vendors Natural Earth.
