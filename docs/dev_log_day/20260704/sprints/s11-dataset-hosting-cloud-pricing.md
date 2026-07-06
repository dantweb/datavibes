# S11 — Dataset: Hosting & Cloud Pricing (catalog #10)

**Date:** 2026-07-06 · **Type:** Sprint plan + data-source spec · **Status:** ✅ DONE (2026-07-06)

> **As-built note.** Shipped as `datasets/hosting-cloud-pricing/` (`dataset.yaml` +
> `sources.py` + `instance_specs.csv`) green under `pytest` — the trio's one genuinely
> bespoke-adapter dataset, as planned. `cloud-price-list` parses the keyless AWS EC2 offer
> index (on-demand Linux/Shared SKUs → hourly USD) and the Azure Retail Prices API (OData
> `NextPageLink` paging, SKU→vCPU/memory enriched from the committed specs CSV). Processing
> is pure config on the S07 subset: `dedupe` → `sort` → `derive: ratio(...)` (per-vCPU /
> per-GiB) → `derive: minmax_normalize(usd_per_vcpu_hr, invert=true)` → `priceperf_index`.
> **`price_volatility` was cut from v1**: it's a rolling std *across snapshots*, which a
> single `run` can't compute — it populates once ≥2 daily snapshots exist (cross-snapshot
> follow-up). The `volatility` helper is built + unit-tested in the S07 library regardless.
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md)
(public-sources-only: **free, documented HTTP APIs, no scraping**).
**Depends on:** the full SDK (S02–S05) **and the S07 primitive library**. Config-first, but
this is the **one** dataset in the trio that earns a small **bespoke adapter** — cloud
price-list shapes are provider-specific and unique enough that no generic adapter covers
them cleanly (exactly the r01 "bespoke where needed" case).
**Catalog basis:** [`../reports/r01-dataset-catalog-coverage.md`](../reports/r01-dataset-catalog-coverage.md) row 10.
**Template:** [`s06-first-dataset-us-regional-weather.md`](s06-first-dataset-us-regional-weather.md).

**Trigger.** Fourth production dataset — a normalised, cross-provider price/performance matrix
for comparable compute instances, tracked over time so buyers see both level and volatility.

---

## Dataset brief

| Field | Value |
|---|---|
| **Topic** | Hosting & Cloud Compute Pricing |
| **Data sources (free APIs)** | AWS Price List Bulk API (no auth), Azure Retail Prices API (no auth), GCP/Hetzner/DO as optional additions |
| **Statistical preprocessing** | Price/performance **min-max normalization**, price **volatility** (rolling std across snapshots) |
| **Value proposition** | Apples-to-apples cross-cloud price/perf intelligence + price-movement signals |
| **Target buyers** | DevOps/platform teams, FinOps, cloud resellers, procurement |
| **Update regularity** | Daily (prices change; volatility needs the daily series) |
| **Size per update** | 5–15 MB |

---

## The whole developer experience

```
datasets/hosting-cloud-pricing/
├── dataset.yaml     # metadata + schema + sources + processing (declarative)
└── sources.py       # ONE small adapter: cloud-price-list (per-provider shape → common rows)
```
```bash
datavibes new hosting-cloud-pricing --category infrastructure
datavibes validate hosting-cloud-pricing && datavibes run hosting-cloud-pricing
```

### `dataset.yaml`
```yaml
metadata:
  slug: hosting-cloud-pricing
  title: Hosting & Cloud Compute Pricing — Price/Performance Matrix
  category: infrastructure
  license: "Public vendor price lists (informational); see attribution"
  update_frequency: daily
  attribution: "AWS Price List; Azure Retail Prices API; provider public pricing"

schema:
  - { name: provider,         dtype: str }              # aws | azure | gcp | hetzner | do
  - { name: region,           dtype: str }
  - { name: instance_type,    dtype: str }
  - { name: vcpu,             dtype: float, unit: "count" }
  - { name: memory_gib,       dtype: float, unit: "GiB" }
  - { name: usd_per_hour,     dtype: float, unit: "USD/hr" }
  - { name: usd_per_vcpu_hr,  dtype: float, unit: "USD/hr", nullable: true }
  - { name: usd_per_gib_hr,   dtype: float, unit: "USD/hr", nullable: true }
  - { name: priceperf_index,  dtype: float, nullable: true, description: "0–1 min-max normalized price/perf" }
  - { name: price_volatility, dtype: float, nullable: true, description: "rolling std of usd_per_hour across snapshots" }

sources:
  - type: cloud-price-list      # bespoke adapter in sources.py (per-provider normaliser)
    providers:
      - { name: aws,   service: AmazonEC2, region: us-east-1 }
      - { name: azure, service: "Virtual Machines", region: eastus }
    families: [general-purpose]  # restrain the row count to comparable on-demand Linux instances

processing:
  - normalize                                             # coerce dtypes/units; drop non-comparable SKUs
  - dedupe:    { keys: [provider, region, instance_type] }
  - derive:    { column: usd_per_vcpu_hr, expr: "usd_per_hour / vcpu" }
  - derive:    { column: usd_per_gib_hr,  expr: "usd_per_hour / memory_gib" }
  - derive:    { column: priceperf_index, expr: "minmax_normalize(usd_per_vcpu_hr, invert=true)" }
  - derive:    { column: price_volatility, expr: "volatility(usd_per_hour, window=30)" }
  - validate
```

**Every promise → an existing S07 primitive (except the adapter):**

| Dataset promise | S07 step/helper |
|---|---|
| Price/perf **normalization** | `minmax_normalize(col, invert)` |
| Price **volatility** | `volatility(col, window)` (rolling std) |
| Per-unit price columns | `derive` (plain arithmetic) |

The **only** non-config code is the `cloud-price-list` adapter (below). `minmax_normalize`
and `volatility` are S07 helpers — not re-implemented here.

---

## The one bespoke adapter — `cloud-price-list` (~1 screen, subclasses `Source`)

Cloud price lists are large, provider-specific JSON with unique paging and SKU shapes. The
adapter normalises each provider to the **common row** `{provider, region, instance_type,
vcpu, memory_gib, usd_per_hour}`; everything downstream is generic.

```python
@register_source("cloud-price-list")
class CloudPriceListSource(Source):
    """Fetch on-demand Linux compute prices per provider → common schema rows."""
    def fetch(self, ctx):
        for p in self.providers:
            if p["name"] == "aws":   yield from self._aws(ctx, p)
            if p["name"] == "azure": yield from self._azure(ctx, p)
    # _aws:   GET the EC2 offer index, walk products×terms → on-demand USD/hr
    # _azure: page prices.azure.com/api/retail/prices via OData NextPageLink
```
It reuses `datavibes.sources.http_client.request_with_retry` (same as the S06 adapter) and
reads **no secrets** — both primary APIs are keyless.

---

## Data sources (all free, all JSON over HTTPS — no scraping)

| Src | Base URL | Auth | Paging | Role |
|---|---|---|---|---|
| A | `https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/<region>/index.json` | **none** | single large doc | AWS EC2 on-demand (backbone) |
| B | `https://prices.azure.com/api/retail/prices` | **none** | OData `NextPageLink` | Azure VM retail prices |
| C | GCP Cloud Billing Catalog `https://cloudbilling.googleapis.com/v1/services/.../skus` | **key** | `nextPageToken` | *optional* — needs `GCP_API_KEY` |
| D | Hetzner / DigitalOcean sizes APIs | **token** | — | *optional* — token-gated, added later |

**A — AWS Price List Bulk (region-scoped, no auth)**
```bash
curl 'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json'
```
```json
{ "products": {
    "ABC123": {"attributes":{"instanceType":"m5.large","vcpu":"2","memory":"8 GiB",
      "operatingSystem":"Linux","tenancy":"Shared","location":"US East (N. Virginia)"}}},
  "terms": {"OnDemand": {"ABC123": {"…":{"priceDimensions":{"…":
      {"pricePerUnit":{"USD":"0.0960000000"},"unit":"Hrs"}}}}}} }
```
Adapter walks `products` for Linux/Shared SKUs, joins each to its `terms.OnDemand` USD/hr.

**B — Azure Retail Prices (OData, no auth, paged)**
```bash
curl -G 'https://prices.azure.com/api/retail/prices' \
  --data-urlencode "\$filter=serviceName eq 'Virtual Machines' and armRegionName eq 'eastus' and priceType eq 'Consumption'" \
  --data-urlencode 'api-version=2023-01-01-preview'
```
```json
{ "Items":[ {"armSkuName":"Standard_D2s_v5","retailPrice":0.096,"unitOfMeasure":"1 Hour",
     "armRegionName":"eastus","productName":"Virtual Machines Dsv5 Series","type":"Consumption"} ],
  "NextPageLink":"https://prices.azure.com/api/retail/prices?...&$skip=100" }
```
Adapter follows `NextPageLink` until null (the generic paging pattern, but the OData filter +
SKU→{vcpu,memory} enrichment is provider-specific → belongs in the adapter, not core).

> **vCPU/memory enrichment:** AWS carries `vcpu`/`memory` inline; Azure SKUs do not, so the
> adapter maps `armSkuName` → specs via a small **committed lookup table** in the dataset
> folder (`instance_specs.csv`) — data, not an API, so still no scraping and fully reproducible.

---

## What this sprint adds to the SDK

**Only the dataset folder** — one bespoke `cloud-price-list` adapter + a committed
`instance_specs.csv`. **No `datavibes/` change**: `minmax_normalize` and `volatility` come
from S07. (If either is absent, that's an S07 gap, fixed in S07.)

## Tests
- **`cloud-price-list` adapter** (network mocked): a recorded AWS EC2 index → correct
  `m5.large` @ 0.096 USD/hr Linux/Shared row; a recorded Azure page + `NextPageLink` walks
  both pages and stops on null; Azure SKU enriched from `instance_specs.csv`; unknown SKU →
  skipped, not crash.
- **End-to-end fixture run**: recorded A+B bodies → golden CSV at the contract path,
  byte-stable under `FixedClock`, exact schema columns.
- **Derive/normalize**: hand-computed `usd_per_vcpu_hr`, `minmax_normalize(invert)` across a
  small provider set, and `volatility` across ≥2 recorded snapshots match pipeline output.
- **Cross-provider comparability**: the fixture asserts AWS and Azure comparable instances
  land on the same `vcpu`/`memory_gib` grid so `priceperf_index` is apples-to-apples.

## Scope
**IN:** the `hosting-cloud-pricing/` dataset folder (`dataset.yaml`, `cloud-price-list`
adapter, `instance_specs.csv`) + the tests above.
**OUT:** GCP/Hetzner/DO token-gated providers (optional follow-up), reserved/spot pricing
(on-demand only for v1), and the GitHub Actions cron (shared follow-up).

## Definition of done
- [ ] `datavibes validate hosting-cloud-pricing` passes; `run` writes
      `output/infrastructure/hosting-cloud-pricing-<hash>/<ts>.csv`.
- [ ] Exactly **one** bespoke adapter (+ committed specs CSV); **nothing** in `datavibes/`
      changed — `minmax_normalize`/`volatility` are reused from S07.
- [ ] Adapter, end-to-end fixture, and derive/volatility tests green with **zero** live network.
- [ ] Golden CSV byte-stable under a fixed clock; a valid snapshot is produced from the
      keyless sources (AWS + Azure) alone.
