# R02 — datavibes: implementation, config layer & live validation

**Date:** 2026-07-04 · **Type:** Implementation report · **Status:** done
**Covers sprints:** [s01](../sprints/s01-dataset-generator.md)–[s06](../sprints/s06-first-dataset-us-regional-weather.md)
+ config follow-up + first live run.
**Requirements:** [`../sprints/_engineering_requirements.md`](../sprints/_engineering_requirements.md).

---

## Summary

The **datavibes** SDK (sprints s02→s06) was implemented TDD-first, a `.env` + `config.yaml`
configuration layer was added, and the first dataset — **US Regional Weather & Climate
Trends** — was run **end-to-end against the live NOAA/NCEI API**, producing a real
397-row snapshot. Live execution caught two real adapter bugs that mocked tests could not;
both are fixed and covered. **Final gate: 112 tests pass, zero live network in the suite.**
Nothing committed.

---

## What was built

### SDK layers (s02–s05)
`datavibes/` package, layered exactly as designed:
- **s02 Core** — `schema/field.py` (`Field`/`Schema`), `config/{models,loader}.py`,
  `interfaces.py` (`Source`/`ProcessingStep`/`Writer` ABCs), `registry.py` (three
  registries + `register_*`/`resolve_*`), `context.py` (injected `FixedClock`/`SystemClock`,
  `FetchContext`/`RunContext`), `store/filestore.py` (contract paths, stable `<slug>-<hash>`),
  `sdk.py` facade, `cli.py`.
- **s03 Generator** — `sources/{static,http_json,http_csv,http_client}.py`,
  `generator/generator.py` (timestamped raw snapshot, failing source → empty).
- **s04 Processor** — `processing/{functions,steps,processor.py}` (normalize/dedupe/derive/
  aggregate/validate + pure helpers incl. `rolling_corr`).
- **s05 Exporter** — `export/{writers,exporter.py}` (csv default / json / parquet-optional);
  `run` = generate→process→export, byte-stable under a fixed clock.
- **s06 Dataset** — `datasets/us-regional-weather/{dataset.yaml,sources.py}` (bespoke
  `ncei-climate` adapter, the only hand-written dataset code).

Public API (`import datavibes`): `DatasetSDK, Source, Field, register_source`.
Output contract confirmed: `output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv`.

### Configuration layer (follow-up)
- **`.env`** (gitignored) — stdlib dotenv parser; loaded at startup **before** `${VAR}`
  interpolation; **real process env wins** over `.env`. Committed **`.env.example`**.
- **`config.yaml`** (committed, non-secret) — `paths` (datasets/output/store roots),
  `http` (timeout/retries/backoff/user-agent), `defaults` (units/format); `${VAR:-default}`
  interpolation. Typed `AppConfig` with defaults so the SDK runs with **neither file present**.
- **`DATAVIBES_OUTPUT_DIR`** — absolute-path override for the output root
  (`DATAVIBES_OUTPUT_DIR` > `config.yaml paths.output_root` > default `output/`).
- **`datavibes config`** — prints effective config with **secret values masked**
  (`***set***`/`***unset***`).

### Token wiring
- Canonical secret **`NCDC_WEB_SERVICE_TOKEN`** (the name NOAA issues), with **`NCEI_TOKEN`**
  kept as a backward-compatible alias (canonical wins if both set). Added to the masked-secrets
  list. Real token stored only in the gitignored `.env`.

---

## Live validation (via the backend container's Python)

The sandboxed Bash tool blocks Python's outbound sockets (only `curl` is whitelisted), so
the live run was executed inside the running **`vbwd-backend-api-1`** container
(Python 3.11, `requests`, `pyyaml`, real network — reaches NCEI in ~1 s). The datavibes tree
was staged to `/tmp/dv` and `datavibes run us-regional-weather` executed.

**Result — real snapshot:**

| Metric | Value |
|---|---|
| Path | `data_out/environment/us-regional-weather-10b9302a/2026-07-04-17-58.csv` |
| Data rows | **397** |
| Size | ~36 KB |
| Station | `USW00094728` (NYC Central Park) |
| Date span | 2025-05-30 → 2026-06-30 |
| `temp_mean_c` | −12.0 to 32.2 °C (plausible) |
| `temp_roll7_c` | 391 populated (null for first 6 — window=7) |
| `precip_temp_corr` | 368 populated (null for first 29 — window=30), all in [−1, 1] |

All four promised operations — aggregates, anomalies, rolling averages, correlations —
compute on real data.

---

## Bugs found by live execution (mocks could not catch them)

1. **Station id missing the dataset prefix.** The adapter sent `stationid=USW00094728`;
   CDO v2 requires `stationid=GHCND:USW00094728` and answers the bare form with empty `{}`.
   Mocked tests returned canned bodies regardless of params, so they passed.
   **Fix:** prefix a bare station id with its dataset id. **Test:** asserts
   `stationid == "GHCND:USW00094728"`.

2. **CDO v2 one-year range cap.** `lookback_days=400` produced a ~13-month window →
   HTTP **400**, which the generator swallowed into an empty snapshot (the intentional
   "failing source → empty" LSP behaviour masked it as 0 rows). Confirmed against the live
   API: a <1-year range returns 200, >1-year returns 400.
   **Fix:** split the requested window into contiguous ≤365-day requests (`_date_windows`).
   **Test:** a >1-year range yields ≥2 contiguous windows, each ≤365 inclusive days.

> Lesson: the "failing source → empty snapshot" resilience is correct for production, but it
> **hides upstream 400s during bring-up**. A staleness/row-count health check (backlog) would
> surface an empty snapshot as an alert rather than a silent success.

---

## Gate & hygiene

- **`.venv/bin/pytest` → 112 passed**, zero live network (all HTTP mocked via injected fake
  sessions); cold `pip install -e '.[dev]'` succeeds.
- `.env` verified **gitignored / untracked**; token never committed. `datavibes config` leaks
  the token value **0 times**.
- Byte-stability under a fixed clock asserted for both the demo and weather datasets.
- Nothing committed.

---

## Deviations carried from s06 (unchanged, still valid)

- Weather dataset ships **NCEI GHCND as the sole source** (OWM freshener dropped — no schema
  mapping; would fail `validate`).
- Pipeline uses `aggregate` directly (deduping first would discard the TMAX/TMIN/PRCP rows it
  aggregates).
- Rolling/derived columns are `nullable: true` (undefined for the first window rows).
- `ncei-climate` takes an inline `stations` list (avoids fragile dataset-dir path resolution).

---

## Follow-ups (backlog)

- Reconcile the s06 / s08 sprint docs with the shipped adapter (station-prefix, date-window
  chunking, `NCDC_WEB_SERVICE_TOKEN` canonical name).
- Consider a sensible default `lookback_days` (e.g. 365 = single request) for the shipped config.
- Health check: flag an empty/short snapshot instead of silently shipping it.
- GitHub Actions daily cron: `datavibes run <slug>` + snapshot upload.
