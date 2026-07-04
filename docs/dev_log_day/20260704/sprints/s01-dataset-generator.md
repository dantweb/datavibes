# S01 — Dataset Generator scaffolding (`datavibes` SDK)

**Date:** 2026-07-04 · **Type:** Sprint plan · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md)
(TDD-first · DevOps-first · SOLID via registries · DI · DRY · deterministic ·
CLI-only + importable · public-sources-only).

**Trigger.** The product brief (2026-07-04, "fully automated, zero-support" model)
requires each dataset to be collected by a **GitHub Actions cron** and delivered
hands-off. Phase 1 (Hosting Benchmarks) and Phase 2 (EU Tech Job Market) both repeat
the *same shape*: collect from public APIs → process → emit a versioned snapshot. This
sprint builds that shape **once**, as a reusable SDK, so every future dataset is
**declarative config + a tiny optional adapter**, not a new bespoke script.

**Area.** NEW standalone repo `datavibes/` (Python 3.11). One console script
(`datavibes`) + an importable package (`datavibes`). **No server, no DB,
no billing** — those live in the VBWD `dataset` plugin ([[project_s110_datasets_plugin]]),
which consumes the files this tool writes.

---

## The one architectural rule this sprint enforces

> **The SDK holds all reusable machinery; a dataset is data, not code.** Every piece
> of behaviour that is *the same across datasets* (fetching, snapshotting, normalising,
> deriving, exporting, on-disk layout) lives in `datavibes/`. Every piece that is
> *specific to one dataset* (which URL, which fields, which derived columns) lives in
> `datasets/<slug>/dataset.yaml`. Bespoke code (a `Source` subclass) is allowed **only**
> when a source cannot be expressed by a built-in adapter, and it plugs in through the
> **source registry** — never by editing the SDK.

Consequence: adding "Hosting Benchmarks" = write one `dataset.yaml` (+ maybe a 20-line
`sources.py`). Adding "EU Tech Job Market" = another `dataset.yaml`. The pipeline code
is written once and never touched again.

---

## Pipeline (the shape built once)

```
  dataset.yaml
      │  load + validate (config)
      ▼
  ┌──────────┐   fetch()    ┌───────────┐  write raw   ┌────────────┐  steps[]   ┌──────────┐  write
  │ SOURCES  │ ───────────▶ │ GENERATOR │ ───────────▶ │ PROCESSOR  │ ─────────▶ │ EXPORTER │ ─────▶ snapshot.csv
  │ registry │  records     │ snapshot  │  raw records │  pure fns  │  rows      │ writers  │
  └──────────┘              └───────────┘              └────────────┘            └──────────┘
        ▲                          │                          ▲                        │
        │                          ▼                          │                        ▼
   built-in + custom          store/raw/<slug>/…        schema (Field[])        store/output/<cat>/<slug>-<hash>/<ts>.csv
```

Each stage is independently runnable from the CLI (`generate`, `process`, `export`) and
composed by `run`.

---

## Building blocks

### 1. `Field` / `Schema` — typed columns (`datavibes/schema/`)
Declarative column spec: `name`, `dtype` (`str|int|float|bool|date`), `nullable`,
`unit`, `description`, optional `transform` (named, pure). `Schema` = ordered
`list[Field]`; it *validates* a processed row set and *orders* the exported columns.
The schema is the single source of truth for the output shape — the exporter never
guesses columns.

### 2. `Source` + registry (`datavibes/sources/`)
```python
class Source(ABC):
    @abstractmethod
    def fetch(self, ctx: FetchContext) -> Iterable[dict]: ...
```
- **Registry**: `register_source("name")` decorator → `SOURCE_REGISTRY["name"]`. The
  config loader resolves a `type:` string to a registered class (OCP seam).
- **Built-in adapters** (cover the "green/easy" datasets from the brief with zero code):
  - `http_json` — GET a JSON API, JSONPath-select the record array.
  - `http_csv` — GET a CSV, stream rows.
  - `static` — inline/fixture records (tests + `new` scaffolding).
- **Custom adapters**: a dataset drops `datasets/<slug>/sources.py`, decorates a
  subclass with `@register_source(...)`, and references it by `type:` in yaml. The SDK
  is untouched.
- `FetchContext` carries the **injected clock**, config, and an HTTP session (DI — no
  module-level network client; determinism req. §7).

### 3. `Generator` (`datavibes/generator/`)
Orchestrates `sources[] → raw records`, tags each record with its source, and writes a
**timestamped raw snapshot** under `store/raw/<slug>/<ts>.jsonl`. Idempotent per
`(slug, timestamp)`. A source that yields nothing → empty snapshot, never a crash (LSP).

### 4. `Processor` + steps (`datavibes/processing/`)
```python
class ProcessingStep(ABC):
    @abstractmethod
    def apply(self, rows: list[dict], ctx) -> list[dict]: ...
```
Ordered, **pure** steps declared in yaml. Built-ins map straight onto the brief's
"Data Processing" tasks:
- `normalize` — coerce to schema dtypes/units.
- `dedupe` — by key columns.
- `derive` — computed columns (e.g. year-over-year change), pure expressions.
- `aggregate` — group/reduce (e.g. median salary by region/skill).
- `validate` — assert rows conform to `Schema`; fail the run loudly if not.
Because steps are pure `list[dict] -> list[dict]`, each is unit-tested with a fixture
(TDD req. §1). New step = register into the step registry; no SDK edit.

### 5. `Exporter` / writers (`datavibes/export/`)
`Writer` per format: `csv` (default, matches the delivery contract), `json`,
`parquet`. Columns and order come from `Schema`. Writes to the **output contract path**.

### 6. `store` (`datavibes/store/`)
Owns the on-disk layout and the `<slug>-<hash>` folder identity. Raw snapshots vs.
processed output are separate trees. Output path:
`output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv` — the exact shape the VBWD
`dataset` plugin serves (verified against
`var/dataset/datasets/environment/air-quality-01a59960/2026-06-01-00-00.csv`).

### 7. `DatasetSDK` facade (`datavibes/sdk.py`)
The importable entrypoint that wires config → sources → generator → processor →
exporter with injected `clock` + `filestore`. Methods: `list()`, `validate(slug)`,
`generate(slug)`, `process(slug)`, `run(slug)`, `export(slug, fmt)`,
`dataset(slug).latest()`. The CLI is a thin argparse shell over this facade — **one
behaviour, two front doors** (req. §8).

---

## `dataset.yaml` — the whole per-dataset contract

```yaml
metadata:
  slug: hosting-benchmarks
  title: Cloud Hosting Benchmarks
  category: infrastructure
  license: CC-BY-4.0
  update_frequency: daily
  attribution: "AWS / Hetzner / DigitalOcean public pricing"

schema:
  - { name: provider, dtype: str }
  - { name: region,   dtype: str }
  - { name: instance, dtype: str }
  - { name: usd_per_hour, dtype: float, unit: USD/h }
  - { name: yoy_change_pct, dtype: float, unit: "%" }

sources:
  - type: http_json
    url: https://api.example.com/pricing
    select: "$.items[*]"
  - type: hetzner-pricing        # custom, from datasets/<slug>/sources.py

processing:
  - normalize
  - dedupe: { keys: [provider, region, instance] }
  - derive: { column: yoy_change_pct, expr: yoy(usd_per_hour) }
  - validate
```

`new <slug>` scaffolds exactly this (with a `static` source) so a dataset boots green
before any real API is wired.

---

## CLI surface (the only human interface)

| Command | Does |
|---|---|
| `datavibes list` | list known datasets + metadata |
| `datavibes new <slug> --category <c>` | scaffold `datasets/<slug>/dataset.yaml` |
| `datavibes validate <slug>` | load config, check schema + sources resolve |
| `datavibes generate <slug>` | fetch sources → raw snapshot |
| `datavibes process <slug>` | latest raw → processed rows |
| `datavibes run <slug>` | generate + process + export (the cron target) |
| `datavibes export <slug> --format csv\|json\|parquet` | re-export processed |
| `datavibes info <slug>` | show latest snapshot path + row count |

GitHub Actions cron = `datavibes run <slug>` on a schedule, then commit/upload
the snapshot. Nothing else.

---

## Scope decision — what MVP is and is NOT

### IN (S01)
- Package skeleton + `pyproject.toml` with the `datavibes` console script.
- `Field`/`Schema`; `Source` ABC + registry + `http_json` / `http_csv` / `static`.
- `Generator` (raw snapshot) + `Processor` with `normalize` / `dedupe` / `derive` /
  `aggregate` / `validate`.
- `csv` writer + `store` implementing the output contract path.
- `DatasetSDK` facade + argparse CLI (`list/new/validate/generate/process/run/export/info`).
- One end-to-end **fixture dataset** (`static` source) proving byte-stable `run`.
- Unit tests per pure step + one CLI smoke test. `pip install -e .` cold-start green.

### OUT (later sprints)
- Real Phase-1 (Hosting Benchmarks) and Phase-2 (EU Tech Job Market) configs — S02+.
- `parquet`/`json` writers beyond a stub, health-check/staleness alerts, RapidAPI sync.
- Any scheduling, delivery, billing, or entitlement logic (belongs to the plugin).
- Network-recording test harness beyond simple mocks.

---

## SOLID mapping (binding req. §3)

- **SRP** — Source fetches; Generator snapshots; Processor transforms; Exporter writes;
  store owns layout.
- **OCP** — source registry + step registry: new dataset/source/step adds a
  registration, never a core edit.
- **LSP** — every `Source`/`ProcessingStep` honours its narrow contract; empty/failed
  source ⇒ empty snapshot, not a mid-pipeline crash.
- **ISP** — `Source`, `ProcessingStep`, `Writer` are single-method interfaces.
- **DIP** — pipeline depends on those abstractions + config + injected clock/filestore,
  never on a concrete provider or on the wall clock.

## Definition of done

- [ ] `pip install -e .` on a cold clone; `datavibes --help` works.
- [ ] `datavibes new demo --category test && datavibes run demo` writes
      `output/test/demo-<hash>/<ts>.csv` and is **byte-stable** across runs with a fixed
      injected clock.
- [ ] Every processing step + the store path builder unit-tested; CLI smoke test green.
- [ ] Output path matches the `dataset` plugin's served shape (verified against a real
      `air-quality-*` snapshot).
- [ ] README + this sprint doc describe the SDK vs. config split accurately.
