# R05 — Publishing the S12 batch to vbwd.cc

**Date:** 2026-08-11 · **Type:** run evidence · **Status:** done
**Sprint:** [`../sprints/s12-catalog-primitives-and-datasets.md`](../sprints/s12-catalog-primitives-and-datasets.md)

13 datasets published to production through the `dataset` plugin's admin API
(`bin/upload_datasets.py` in the SDK repo). Files are never hand-copied onto the
VPS — the API is the only sanctioned path.

## Result

| | |
|---|---|
| Live catalogue | **15** datasets (13 new + `ev-share-production`, `us-reg-weather`) |
| Categories | `infrastructure` 6 · `environment` 4 · `energy` 3 · `macro` 2 — none uncategorised |
| New category terms created | `infrastructure`, `macro`, `energy` |
| Per dataset | 1 primary CSV + 3 documents (report.pdf, analytics.md, statistics.md) + 3-4 chart PNGs |
| Integrity | every primary CSV's sha256 matches the local file — **0 mismatches** |
| Re-run | second run wrote nothing (26 skip lines) — idempotent |

Two exclusions, both deliberate: `us-regional-weather` (0 rows — publishing an
empty dataset into a paying catalogue is wrong, and the uploader refuses
zero-row snapshots outright) and `vehicle-production-ev-share` (production
already carries that data as `ev-share-production`; publishing would duplicate
it under a second slug).

## The blocker: the plugin's permissions were never granted

`claude26@vbwd.cc` authenticated and passed `@require_admin`, but every
`/api/v1/admin/datasets*` call returned **403 `{"required": "dataset.view"}`**.
The cause was not the account — it was the instance: **no role on vbwd.cc
carried `dataset.view` or `dataset.manage`**, even though the `dataset` plugin
is enabled and serving the public catalogue. The fe-admin dataset UI was
therefore 403ing for every admin, not just for this run.

Fixed with the operator's approval by granting both permissions to the `admin`
role (17 → 19). `super_admin` holds the wildcard `*` and would also have
satisfied the guard with no RBAC change — worth remembering as the
zero-mutation route.

> ⚠️ **`_assign_permissions` REPLACES, it does not merge.**
> `vbwd/routes/admin/access.py` calls `role.permissions.clear()` before re-adding
> whatever the request body lists. `PUT /admin/access/roles/<id>` with
> `{"permissions": ["dataset.view", "dataset.manage"]}` would have **deleted the
> admin role's other 17 permissions** and locked every admin out of the platform.
> Always send the existing set plus the additions, and diff the response for
> lost entries. The original 17 were backed up to disk before the write.

## Gotchas for the next publisher

- The admin snapshot-files response is keyed **`files`** (primary-first, the
  primary carrying `id: "primary"`), and dataset-category assignment returns
  **`{"term_ids": [...]}`** — not `items`/`categories`. Three verification passes
  misread these before checking the raw body; the uploads were correct each time.
- The catalogue is category-first: a dataset with no `dataset_category` term
  renders an empty `/datastore` however many rows it has. Every publish assigns
  a term at creation.
- datavibes slugs and production slugs are not the same namespace
  (`vehicle-production-ev-share` vs `ev-share-production`). Diff against the live
  catalogue before publishing or you create a twin.
