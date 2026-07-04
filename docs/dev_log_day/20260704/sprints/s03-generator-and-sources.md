# S03 — Generator & source adapters

**Date:** 2026-07-04 · **Type:** Sprint plan · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md).
**Depends on:** [`s02-core-services-models-interfaces.md`](s02-core-services-models-interfaces.md)
(interfaces, registries, store, `FetchContext`, clock).

**Trigger.** With the backbone in place, the first live stage is **collection**: turn a
dataset's declared `sources[]` into a timestamped **raw snapshot**. This sprint ships the
built-in source adapters + the `Generator` that orchestrates them.

**Area.** `datavibes/sources/` + `datavibes/generator/`.

---

## The one rule this sprint enforces

> **A source only fetches; the generator only snapshots.** Adapters return an iterable of
> plain `dict` records and know nothing about schema, storage, or timestamps. The
> generator owns tagging, ordering, and writing the raw snapshot. A source that yields
> nothing or errors produces an **empty snapshot**, never a mid-run crash (LSP).

---

## Deliverables

### 1. Built-in source adapters — `datavibes/sources/`
All registered via `@register_source(...)` (S02 registry), constructed from
`SourceSpec.options`, fetching through the **injected** `ctx.http` session — no
module-level client (DI + determinism).

- `static` (`static.py`) — yields inline/fixture records from `options["records"]` or a
  referenced fixture file. Used by `new` scaffolding + tests; needs no network.
- `http_json` (`http_json.py`) — GET `url`, JSONPath-`select` the record array,
  optional `headers`/`params`. Retries with backoff; non-2xx → typed `SourceFetchError`.
- `http_csv` (`http_csv.py`) — GET `url`, stream CSV rows to dicts (header-driven),
  optional `delimiter`/`encoding`.

**Tests (network mocked — CI never hits a live API):**
- `static` yields exactly the configured records.
- `http_json` selects the right nodes from a recorded JSON body; `select` miss →
  empty, not crash; non-2xx → `SourceFetchError` with url + status.
- `http_csv` parses a fixture CSV incl. quoted fields + custom delimiter.
- Retry/backoff invoked on transient 5xx (mocked), gives up after N.

### 2. Generator — `datavibes/generator/generator.py`
- `Generator(store, clock)`; `generate(config: DatasetConfig) -> RawSnapshot`:
  1. resolve each `SourceSpec` → `Source` via registry;
  2. `fetch(ctx)` each, tagging every record with `_source` = spec type/index;
  3. concatenate in declared source order (deterministic);
  4. `store.write_raw(slug, ts=clock.now())` as JSONL, returning the path + row count.
- Idempotent per `(slug, timestamp)` — re-running with the same `FixedClock` overwrites
  to identical bytes.
- One failing source is logged and skipped (empty contribution); the run still produces a
  snapshot of the healthy sources.

**Tests:**
- Two `static` sources → merged, source-tagged, order-stable snapshot.
- `FixedClock` ⇒ byte-identical raw file across two runs (determinism).
- One source raises → snapshot still written from the others; failure surfaced in result.
- Empty dataset (all sources empty) → valid empty snapshot, no exception.

### 3. Facade + CLI wiring
- `DatasetSDK.generate(slug)` loads config → `Generator.generate` → returns snapshot info.
- `datavibes generate <slug>` prints the raw path + row count.
- **Tests:** CLI `generate` on a `static`-source fixture writes the expected
  `store/raw/<slug>/<ts>.jsonl` and reports the row count.

---

## Scope
**IN:** `static` / `http_json` / `http_csv` adapters, `Generator`, facade+CLI `generate`,
all with mocked-network tests.
**OUT:** processing/derivation (S04), export to CSV output-contract path (S05), any
dataset-specific adapter (S06+).

## SOLID mapping
- **SRP** — adapters fetch; generator snapshots; store persists.
- **OCP** — new source = new `@register_source` class, generator untouched.
- **LSP** — every adapter honours `fetch(ctx) -> Iterable[dict]`; failure degrades gracefully.
- **DIP** — generator depends on `Source`/registry/store/clock abstractions only.

## Definition of done
- [ ] `datavibes generate <fixture>` writes a raw JSONL snapshot; row count reported.
- [ ] All adapter + generator tests green with **zero** live network calls.
- [ ] Same config + `FixedClock` ⇒ byte-stable raw snapshot.
- [ ] A failing source never aborts the run.
