# Configuring charts

Charts are declared **per dataset** in `dataset.yaml`, under a top-level
`charts:` list. When a report is generated (`datavibes run <slug>` with
`report.charts: true`, or `datavibes report <slug>`), each chart is rendered to
a PNG in the dataset's output folder under `charts/` and embedded in
`report.pdf`.

```
output/<slug>/
├── <timestamp>.csv        # the snapshot
├── analytics.md
├── statistics.md
├── charts/
│   ├── 01-<title>.png
│   └── 02-<title>.png
└── report.pdf             # charts embedded
```

Charts operate on the **processed rows** (post-`processing`), i.e. the same rows
that land in the CSV. Rendering needs the optional `matplotlib` dependency
(`pip install 'datavibes[report]'`); a chart that can't be built (missing
column, no numeric data) is skipped with a warning — it never fails a run.

---

## Minimal example

```yaml
charts:
  - type: bar
    title: "Top renewable-electricity countries (2022)"
    x: country
    y: renewable_elec_pct
    filter: { year: 2022 }
    sort:   { by: renewable_elec_pct, desc: true }
    limit:  15
```

---

## Field reference

| Field | Required | Type | Meaning |
|---|---|---|---|
| `type` | ✅ | `bar` \| `line` \| `scatter` \| `area` | Chart kind (see below). |
| `title` | ✅ | string | Chart title; also the figure caption and the PNG filename. |
| `x` | ✅ | column name | The category/axis column. |
| `y` | ✅ | column name | The numeric value column (coerced to float; non-numeric rows dropped). |
| `series` | — | column name | Split into one line/curve per distinct value of this column. |
| `agg` | — | `mean` \| `sum` \| `median` \| `min` \| `max` | How to reduce multiple rows that share the same `x` (default `mean`). Ignored when `series` is set or for `scatter`. |
| `filter` | — | mapping | Keep only rows where each `column: value` matches exactly (string-compared). |
| `sort` | — | `{ by: <col>, desc: <bool> }` | Order the points. `by` is usually `y` (the value) or `x`. `desc: true` for descending. |
| `limit` | — | int | Keep only the first N points after sorting (e.g. "top 15"). |

### Chart types

- **`bar`** — one bar per `x` category. Rows sharing an `x` are reduced by `agg`.
  Pair with `sort: {by: <y>, desc: true}` + `limit` for a "top-N" ranking.
- **`line`** — a trend across `x` (typically a time column like `year`). With
  `series`, draws one line per series value (e.g. one line per country).
- **`area`** — a filled line; same inputs as `line` (single series).
- **`scatter`** — raw `(x, y)` points; both must be numeric. Good for
  correlation views. `agg`/`sort`/`limit` do not apply.

### Aggregation vs. series

- Use **`agg`** when many rows map to one `x` and you want a single value per
  category (e.g. average price per provider).
- Use **`series`** when you want to keep the rows separate as multiple curves
  (e.g. EV share per year, one line per country).

---

## Worked examples

**Ranked bar (top-N after filter + sort):**
```yaml
- type: bar
  title: "Cheapest instances by price per vCPU-hour"
  x: instance_type
  y: usd_per_vcpu_hr
  agg: min
  sort: { by: usd_per_vcpu_hr, desc: false }
  limit: 12
```

**Multi-series line (one line per country over time):**
```yaml
- type: line
  title: "EV sales share over time — selected markets"
  x: year
  y: ev_share_pct
  series: country
```

**Scatter (correlation):**
```yaml
- type: scatter
  title: "EV share vs. charging points"
  x: charging_points
  y: ev_share_pct
```

---

## Styling & the PDF

Charts use a restrained, professional palette and are embedded (as inline
`data:` URIs) into the report PDF, which is rendered from the HTML template
packaged at `datavibes/report/templates/report.html` (New-York-consultancy house
style) — it ships inside the wheel, so a `pip install`-only datavibes renders the
full report. Point `report.template` in `config.yaml` at a copy of that file to
restyle every report. The PDF uses WeasyPrint when available (`pip install
'datavibes[report-html]'`); without it, datavibes falls back to a plainer
built-in PDF that still embeds the same charts.

Toggle chart rendering globally with `report.charts` in `config.yaml`.
