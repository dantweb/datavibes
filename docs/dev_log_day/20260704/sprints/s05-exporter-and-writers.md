# S05 — Exporter & writers

**Date:** 2026-07-04 · **Type:** Sprint plan · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md).
**Depends on:** [`s02-core-services-models-interfaces.md`](s02-core-services-models-interfaces.md)
(`Writer`, writer registry, `Schema`, store/output-contract path) and
[`s04-processor-and-steps.md`](s04-processor-and-steps.md) (processed rows).

**Trigger.** Processed rows must land as a **versioned snapshot file** at the exact path
the VBWD `dataset` plugin serves. This sprint ships the format writers + the exporter that
places output at the delivery-contract path — closing the pipeline so `run` works
end-to-end.

**Area.** `datavibes/export/`.

---

## The one rule this sprint enforces

> **The schema decides columns and order; the writer only serialises.** The exporter never
> infers columns from the data — it takes them from `Schema.column_names()`, so the output
> header is stable regardless of row contents. Output path is the delivery contract:
> `output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv`.

---

## Deliverables

### 1. Writers — `datavibes/export/writers.py`
Registered via `@register_writer(...)`, implement `write(rows, schema, dest) -> Path`:

- `csv` (default, matches the plugin's served format) — header from
  `Schema.column_names()`, rows in schema column order, deterministic quoting, `\n` line
  ends, UTF-8, no index column. Byte-stable for identical input.
- `json` — array of objects, schema-ordered keys, sorted deterministically.
- `parquet` — columnar export (optional dep; skipped-with-clear-message if pyarrow absent).

**Tests:**
- `csv` header equals schema order even when row dict key order differs.
- `csv` output is **byte-identical** across two runs of the same rows (determinism).
- `csv` matches a real `air-quality-*/<ts>.csv` sample shape (header + rows).
- `json` keys schema-ordered; `parquet` round-trips or degrades with a clear message.
- Unknown format → `UnknownStrategyError` naming the format.

### 2. Exporter — `datavibes/export/exporter.py`
- `Exporter(store, clock)`; `export(config, rows, fmt="csv") -> Path`:
  resolve writer via registry → `store.output_path(category, slug, clock.now())` → write →
  return the path.
- Creates the `<category>/<slug>-<hash>/` folder on demand; overwrites idempotently for the
  same `(slug, timestamp)`.

**Tests:**
- Export writes to the contract path; folder created; returned path correct.
- Re-export with `FixedClock` ⇒ same path, byte-identical file (idempotent).

### 3. Facade + CLI wiring — closes the pipeline
- `DatasetSDK.export(slug, fmt)` = processed rows → `Exporter.export`.
- `DatasetSDK.run(slug)` = `generate → process → export` composed (the cron target).
- `datavibes export <slug> --format csv|json|parquet` and `datavibes run <slug>`.
- **Tests:** `run` on the `static`-source fixture writes
  `output/<category>/<slug>-<hash>/<ts>.csv`; two runs with `FixedClock` produce identical
  bytes — the full end-to-end determinism guarantee.

---

## Scope
**IN:** `csv`/`json`/`parquet` writers, `Exporter`, facade `export` + `run`, CLI, tests.
**OUT:** health/staleness alerts, RapidAPI sync, real datasets (S06+).

## SOLID mapping
- **SRP** — writers serialise; exporter places; store owns paths.
- **OCP** — new format = new `@register_writer`; exporter untouched.
- **LSP** — every writer honours `write(rows, schema, dest) -> Path`.
- **DIP** — exporter depends on writer registry + store + schema abstractions.

## Definition of done
- [ ] `datavibes run <fixture>` writes the snapshot at the exact delivery-contract path.
- [ ] CSV output byte-identical across repeated runs (fixed clock) and matches the plugin's
      served shape.
- [ ] All writer + exporter tests green from a cold clone.
- [ ] Full pipeline (`generate→process→export`) proven end-to-end by one test.
