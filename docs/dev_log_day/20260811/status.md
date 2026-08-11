# 2026-08-11 — status

## Done today

- **S12 — catalog primitives + dataset batch** ·
  [sprint](sprints/s12-catalog-primitives-and-datasets.md) ·
  [results](reports/r04-s12-dataset-batch-results.md)
  - Closed the primitive gap R01 (2026-07-04) identified: 4 new source adapters,
    6 new processing steps, 8 new derive helpers, all TDD, network mocked.
  - Promoted `worldbank-indicator` out of the energy dataset into the SDK.
  - Authored **11 new datasets** as pure config and ran every one live.
  - `pytest -q` green at 219 tests (52 new).

## Carried forward

- **#23 Global Hosting Performance** — blocked on a benchmark corpus; no keyless
  price/performance feed exists. Bundles with `hosting-cloud-pricing` once it does.
- **`us-regional-weather` has no data** — NOAA NCEI needs `NCDC_WEB_SERVICE_TOKEN`,
  absent from `.env`, so the dataset holds 0 rows. Its `charts:` block was added this
  sprint, so the full bundle renders the moment the token lands; until then its four
  charts are skipped (loudly) and its report is profile-only.
- **#2 US Census** — `api.census.gov` now demands a key. One `.env` line away;
  `paged_http_json` already carries token plumbing.
- **#16 EU TED, #30 municipal procurement, #13 EU regulatory** — the `hhi`/`classify`
  primitives now exist, but each source is a POST-search or gazette scrape. Highest
  price point in the catalog; deserves its own sprint plus a staleness alarm.
- **Snapshot regression alarm** — `run` now *names* a failed source on stderr (fixed in
  this sprint after two datasets shipped green, empty CSVs). Still missing: a snapshot
  whose row count collapses against the previous one should fail loud, not just warn.
- **`sdmx` adapter** — deferred; no reachable endpoint left that needs it.
