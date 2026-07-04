# S04 — Processor & processing steps

**Date:** 2026-07-04 · **Type:** Sprint plan · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md).
**Depends on:** [`s02-core-services-models-interfaces.md`](s02-core-services-models-interfaces.md)
(`ProcessingStep`, step registry, `Schema`, `RunContext`) and
[`s03-generator-and-sources.md`](s03-generator-and-sources.md) (raw snapshot as input).

**Trigger.** The generator produces raw records; the product needs *processed* datasets —
normalised, deduped, with derived columns (year-over-year change, rolling averages,
anomalies) and validated against the schema. This sprint ships those transforms as
**pure, individually testable steps** plus the `Processor` that runs them in declared order.

**Area.** `datavibes/processing/`.

---

## The one rule this sprint enforces

> **Every step is a pure function `list[dict] -> list[dict]` with no I/O.** No step reads
> the clock, the network, or disk; anything time-relative comes from `ctx` (injected
> clock) or from the data itself. This makes each step a one-line unit test with a fixture
> in / fixture out, and makes the whole processor deterministic.

---

## Deliverables

### 1. Built-in steps — `datavibes/processing/steps.py`
All registered via `@register_step(...)`, constructed from `StepSpec.options`:

- `normalize` — coerce every row to the schema (dtypes, units, trimming) via
  `Schema.coerce`; drop/flag unknown columns per `options`.
- `dedupe` — remove duplicates by `options["keys"]`, keeping first/last per `options`.
- `derive` — add a computed column: `options{column, expr}` where `expr` names a pure
  helper (e.g. `yoy(col)`, `rolling_avg(col, window)`, `anomaly(col, baseline)`,
  `pct_change(col)`). Helpers live in `datavibes/processing/functions.py`, each pure +
  unit-tested independently.
- `aggregate` — group by `options["by"]`, reduce `options["metrics"]` (mean/median/min/
  max/count) → one row per group.
- `validate` — assert the result conforms to `Schema`; on violation raise
  `SchemaValidationError` naming column + row (fail loud, never ship bad data).

**Tests (pure, fixtures only):**
- `normalize` casts strings→float/date, rejects bad values.
- `dedupe` collapses dup keys, honours keep-first/last.
- each `derive` helper: `yoy`, `rolling_avg` (edge windows, short series),
  `anomaly` (vs. baseline), `pct_change` (zero-denominator guard).
- `aggregate` median/mean by group; empty group handling.
- `validate` passes clean rows, raises with a precise message on a dtype/null breach.

### 2. Processor — `datavibes/processing/processor.py`
- `Processor(clock)`; `process(config, rows) -> list[dict]`:
  resolve each `StepSpec` → step via registry, fold them over `rows` in declared order,
  passing `RunContext`. A step failure raises with the step name for a legible trace.
- Reads the **latest raw snapshot** via store when driven by the facade; accepts rows
  directly when called in-process (library use).

**Tests:**
- Full chain `normalize → dedupe → derive → aggregate → validate` on a fixture yields the
  expected processed rows (golden file).
- Step order matters: swapping two steps changes output (proves ordered fold).
- A mid-chain `validate` failure aborts with the offending step named.
- Same input + same `FixedClock` ⇒ identical output (determinism).

### 3. Facade + CLI wiring
- `DatasetSDK.process(slug)` = load config → read latest raw → `Processor.process` → hold
  processed rows for export (S05) / return for library callers.
- `datavibes process <slug>` reports processed row count + which steps ran.
- **Tests:** CLI `process` on a fixture with a known raw snapshot yields the golden rows.

---

## Scope
**IN:** the five steps + pure derive-helper library + `Processor` + facade/CLI `process`,
all with fixture tests.
**OUT:** collection (S03), writing to the output-contract CSV path (S05), dataset-specific
derivations (S06 authors those from these primitives).

## SOLID mapping
- **SRP** — one transform per step; processor only sequences.
- **OCP** — new transform = new `@register_step` (or new pure helper); processor untouched.
- **LSP** — every step honours `apply(rows, ctx) -> rows`.
- **DIP** — processor depends on the step registry + `Schema` abstraction, not on concretes.

## Definition of done
- [ ] Each step + each derive helper has its own passing unit test.
- [ ] Golden-file test proves the full ordered chain output.
- [ ] `validate` fails loud on bad data with column + row in the message.
- [ ] `datavibes process <fixture>` produces the golden processed rows deterministically.
