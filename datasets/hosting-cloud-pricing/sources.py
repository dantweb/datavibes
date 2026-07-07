"""Bespoke ``cloud-price-list`` source for the Hosting & Cloud Pricing dataset.

Cloud price lists are large, provider-specific documents with unique shapes and
paging that no generic adapter covers — the r01 "bespoke where needed" case.
This adapter normalises each provider to the common row ``{provider, region,
instance_type, vcpu, memory_gib, usd_per_hour}``; everything downstream
(per-unit ratios, price/perf index) is generic config on the S07 primitives.

* **AWS** — the keyless EC2 offer index (one large JSON): walk on-demand Linux,
  shared-tenancy SKUs and join each to its hourly USD price.
* **Azure** — the keyless Retail Prices API (OData, ``NextPageLink`` paging):
  consumption VM prices enriched with vCPU/memory from a committed specs CSV
  (the API omits instance specs).

No secret is required for either provider.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.sources.http_client import request_with_retry

AWS_INDEX_URL = (
    "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/"
    "{region}/index.json"
)
AZURE_PRICES_URL = "https://prices.azure.com/api/retail/prices"
MAX_PAGES = 100


@register_source("cloud-price-list")
class CloudPriceListSource(Source):
    """Fetch on-demand Linux compute prices per provider → common schema rows."""

    def __init__(
        self,
        providers: list[dict] | None = None,
        specs_file: str = "instance_specs.csv",
    ):
        self.providers = providers or []
        self.specs_file = specs_file

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        rows: list[dict] = []
        for provider in self.providers:
            name = provider.get("name")
            if name == "aws":
                rows.extend(self._fetch_aws(ctx, provider))
            elif name == "azure":
                rows.extend(self._fetch_azure(ctx, provider))
        return rows

    # ---------------------------------------------------------------------- aws
    def _fetch_aws(self, ctx: FetchContext, provider: dict) -> list[dict]:
        region = provider.get("region", "us-east-1")
        url = AWS_INDEX_URL.format(region=region)
        response = request_with_retry(
            ctx.http, url, params={}, headers={}, settings=ctx.http_settings
        )
        body = response.json()
        products = body.get("products", {})
        on_demand = body.get("terms", {}).get("OnDemand", {})
        rows: list[dict] = []
        for sku, product in products.items():
            attributes = product.get("attributes", {})
            if not _is_plain_linux_instance(product, attributes):
                continue
            price = _aws_hourly_usd(on_demand.get(sku, {}))
            if price is None or price <= 0:
                continue
            rows.append(
                {
                    "provider": "aws",
                    "region": region,
                    "instance_type": attributes.get("instanceType"),
                    "vcpu": float(attributes.get("vcpu", 0) or 0),
                    "memory_gib": _parse_gib(attributes.get("memory")),
                    "usd_per_hour": price,
                }
            )
        return rows

    # -------------------------------------------------------------------- azure
    def _fetch_azure(self, ctx: FetchContext, provider: dict) -> list[dict]:
        specs = self._load_specs()
        region = provider.get("region", "eastus")
        service = provider.get("service", "Virtual Machines")
        params = {
            "$filter": (
                f"serviceName eq '{service}' and armRegionName eq '{region}' "
                "and priceType eq 'Consumption'"
            ),
            "api-version": "2023-01-01-preview",
        }
        url: str | None = AZURE_PRICES_URL
        rows: list[dict] = []
        for _ in range(MAX_PAGES):
            if url is None:
                break
            response = request_with_retry(
                ctx.http, url, params=params, headers={}, settings=ctx.http_settings
            )
            body = response.json()
            for item in body.get("Items", []):
                row = _azure_row(item, region, specs)
                if row is not None:
                    rows.append(row)
            url = body.get("NextPageLink")
            params = {}  # NextPageLink already carries the query
        return rows

    def _load_specs(self) -> dict[str, dict]:
        path = Path(__file__).resolve().parent / self.specs_file
        if not path.is_file():
            return {}
        specs: dict[str, dict] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            for entry in csv.DictReader(handle):
                specs[entry["sku"]] = {
                    "vcpu": float(entry["vcpu"]),
                    "memory_gib": float(entry["memory_gib"]),
                }
        return specs


def _is_plain_linux_instance(product: dict, attributes: dict) -> bool:
    return (
        product.get("productFamily") == "Compute Instance"
        and attributes.get("operatingSystem") == "Linux"
        and attributes.get("tenancy") == "Shared"
        and attributes.get("capacitystatus") == "Used"
        and attributes.get("preInstalledSw", "NA") == "NA"
    )


def _aws_hourly_usd(sku_terms: dict) -> float | None:
    for offer in sku_terms.values():
        for dimension in offer.get("priceDimensions", {}).values():
            usd = dimension.get("pricePerUnit", {}).get("USD")
            if usd is not None:
                return float(usd)
    return None


def _azure_row(item: dict, region: str, specs: dict[str, dict]) -> dict | None:
    if item.get("unitOfMeasure") != "1 Hour" or item.get("type") != "Consumption":
        return None
    sku = item.get("armSkuName")
    price = item.get("retailPrice")
    product_name = item.get("productName", "")
    sku_name = item.get("skuName", "")
    # Spot / Low-Priority rows share the same armSkuName but tag their skuName
    # ("... Spot" / "... Low Priority"); Windows is flagged in productName. The
    # skuName format is inconsistent across series (e.g. "Standard_D4s_v5" vs
    # "E2s v5"), so filter by these markers rather than an exact match.
    if not sku or price in (None, 0) or "Windows" in product_name:
        return None
    if "Spot" in sku_name or "Low Priority" in sku_name:
        return None
    spec = specs.get(sku)
    if spec is None:  # cannot compare without vCPU/memory → skip
        return None
    return {
        "provider": "azure",
        "region": item.get("armRegionName", region),
        "instance_type": sku,
        "vcpu": spec["vcpu"],
        "memory_gib": spec["memory_gib"],
        "usd_per_hour": float(price),
    }


def _parse_gib(memory: object) -> float:
    if memory is None:
        return 0.0
    text = str(memory).replace("GiB", "").replace("GB", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0
