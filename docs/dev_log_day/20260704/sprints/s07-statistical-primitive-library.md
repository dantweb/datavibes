# S07 — Statistical primitive library + join / paged / stat-format adapters (30-dataset coverage)

**Date:** 2026-07-04 · **Type:** Sprint plan · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md).
**Depends on:** S02 (registries, `Schema`, interfaces), S03 (source pattern), S04 (step
pattern + pure-helper pattern), S05 (writers).
**Design basis:** [`../reports/r01-dataset-catalog-coverage.md`](../reports/r01-dataset-catalog-coverage.md)
— the row-by-row proof that these primitives cover all 30 catalog datasets.

**Trigger.** The product catalog has **30 datasets**, and the requirement is that *any* of
them renders on datavibes as config (+ occasional small adapter). R01 shows the SDK's
abstractions already fit; what's missing is a **finite, shared** library of built-in
adapters, steps, and pure helpers. This sprint builds that closed set so no dataset after
it needs an SDK change.

**Area.** `datavibes/sources/` (3 generic adapters + decoders) and
`datavibes/processing/` (5 steps + ~9 helpers). **No new architecture** — only concrete
strategies plugged into existing registries.

---

## The one rule this sprint enforces

> **After S07 the primitive set is closed.** Adding datasets #2–#30 must require *zero*
> edits under `datavibes/` beyond a per-dataset `datasets/<slug>/` folder (config + rare
> ~30-line adapter). If a dataset needs a genuinely new *reusable* primitive, that is a
> deliberate S07-follow-up, not an ad-hoc dataset-side hack.

---

## Deliverables

### A. Generic source adapters — `datavibes/sources/`
| Adapter | Contract | Key tests (network mocked) |
|---|---|---|
| `paged_http_json` | token/api-key header + cursor/offset/page paging; yields flattened records | walks N pages to exhaustion; stops at empty page; token header sent; rate-limit 429 → backoff |
| `jsonstat` | decode JSON-stat (Eurostat, e-Stat) → tidy `dimension×value` rows | multi-dimension cube → correct long-form rows; missing-value cells handled |
| `sdmx` | decode SDMX-JSON (World Bank/Eurostat SDMX) → tidy rows | series+observations flattened; attributes mapped |

These three make ~20 of the 30 datasets **config-only**. Bespoke per-dataset adapters
remain the exception (e.g. `ncei-climate` in S06).

### B. Processing steps — `datavibes/processing/steps.py`
| Step | Options | Key tests (pure) |
|---|---|---|
| `join` | `{right: <source/slug>, on: [...], how: left/inner}` | geo/cross-source join; unmatched keys per `how`; no cartesian blow-up |
| `score` | `{column, inputs: {col: weight}, scale}` | weighted composite; missing input → defined behaviour; scale bounds |
| `flag` | `{column, when: <rule>}` | threshold/rule → bool; greenwashing/stress fixture |
| `classify` | `{column, buckets: [...]}` | rule-based bucketing (impact class, tiers); boundary values |
| `forecast` | `{column, horizon, method: linear/holt}` | linear + Holt on known series; horizon length; short-series guard |

### C. Pure derive helpers — `datavibes/processing/functions.py` (each independently tested)
`cagr`, `gini`, `hhi`, `minmax_normalize`, `zscore`, `share`/`penetration`,
`volatility` (rolling std), `seasonal_index`, `corr` (static; `rolling_corr` already exists
from S06).

**Helper test pattern (TDD):** known input series → known scalar/series output; degenerate
cases explicit (empty, single element, zero variance, zero denominator, window > length).
Every helper is a pure function with no I/O — a one-line unit test each.

---

## Scope
**IN:** the 3 generic adapters + decoders, 5 steps, ~9 helpers — all registered into the
existing registries, all with mocked/pure tests; docs updating the "built-in primitives"
list in the README.
**OUT:** the datasets themselves (each is its own follow-up folder), health/staleness
alerts, the GitHub Actions cron, graph/network *rendering* (R01 limits — datavibes emits an
edge-list table at most).

## SOLID mapping
- **SRP** — each adapter/step/helper does exactly one thing.
- **OCP** — all plug into S02 registries; the pipeline code from S03–S05 is untouched.
- **LSP** — adapters honour `fetch`, steps honour `apply`, helpers are pure — substitutable.
- **DRY** — every catalog "statistical preprocessing" phrase resolves to *one* shared
  primitive, defined once here.
- **No overengineering** — the set is derived directly from R01's 30-row matrix; nothing
  speculative is built.

## Definition of done
- [ ] Every adapter, step, and helper in R01's primitive tables exists and is registered.
- [ ] Each has a passing unit test (adapters mocked, steps/helpers pure); suite green from a
      cold clone with **zero** live network.
- [ ] A "catalog coverage" test authors ≥3 representative datasets from R01 (e.g. #4
      Eurostat via `jsonstat`, #8 renewable `share`, #16 procurement `hhi`) **purely as
      config fixtures** and runs each end-to-end to a byte-stable CSV — proving no SDK edit
      is needed per dataset.
- [ ] README "built-in primitives" list matches the shipped set.
