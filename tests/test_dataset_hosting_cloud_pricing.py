"""S11 — Hosting & Cloud Pricing: cloud-price-list adapter + end-to-end run.

Network fully mocked (recorded AWS + Azure bodies). Processing is pure config on
the S07 primitives (ratio / minmax_normalize). Azure paging follows NextPageLink.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.config.loader import load_custom_sources
from datavibes.context import FetchContext, FixedClock
from datavibes.registry import SOURCE_REGISTRY
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse, RecordingSession

DATASET_DIR = Path(__file__).resolve().parents[1] / "datasets" / "hosting-cloud-pricing"
FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))


@pytest.fixture(autouse=True)
def _register_adapter():
    load_custom_sources(DATASET_DIR)


def _aws_body():
    def product(sku, itype, vcpu, mem, os="Linux", tenancy="Shared", pre="NA"):
        return {
            "sku": sku,
            "productFamily": "Compute Instance",
            "attributes": {
                "instanceType": itype, "vcpu": vcpu, "memory": mem,
                "operatingSystem": os, "tenancy": tenancy,
                "capacitystatus": "Used", "preInstalledSw": pre,
            },
        }

    def term(sku, usd):
        return {
            f"{sku}.OFFER": {
                "priceDimensions": {
                    f"{sku}.OFFER.DIM": {"unit": "Hrs", "pricePerUnit": {"USD": usd}}
                }
            }
        }

    return {
        "products": {
            "AAA": product("AAA", "m5.large", "2", "8 GiB"),
            "BBB": product("BBB", "m5.xlarge", "4", "16 GiB"),
            "WIN": product("WIN", "m5.win", "2", "8 GiB", os="Windows"),  # ignored
            "DED": product("DED", "m5.ded", "2", "8 GiB", tenancy="Dedicated"),  # ignored
        },
        "terms": {
            "OnDemand": {
                "AAA": term("AAA", "0.096"),
                "BBB": term("BBB", "0.168"),  # 4 vCPU → 0.042/vCPU (cheapest per-vCPU)
                "WIN": term("WIN", "0.180"),
                "DED": term("DED", "0.200"),
            }
        },
    }


def _azure_page_one():
    return {
        "Items": [
            # True pay-as-you-go Linux row: skuName == armSkuName.
            {"armSkuName": "Standard_D2s_v5", "skuName": "Standard_D2s_v5", "retailPrice": 0.096,
             "unitOfMeasure": "1 Hour", "armRegionName": "eastus", "type": "Consumption",
             "productName": "Virtual Machines Dsv5 Series"},
            # Low-Priority row for the same SKU (cheaper) — must be excluded.
            {"armSkuName": "Standard_D2s_v5", "skuName": "Standard_D2s_v5 Low Priority", "retailPrice": 0.019,
             "unitOfMeasure": "1 Hour", "armRegionName": "eastus", "type": "Consumption",
             "productName": "Virtual Machines Dsv5 Series"},
        ],
        "NextPageLink": "https://prices.azure.com/api/retail/prices?$skip=100",
    }


def _azure_page_two():
    return {
        "Items": [
            {"armSkuName": "Standard_D4s_v5", "skuName": "Standard_D4s_v5", "retailPrice": 0.192,
             "unitOfMeasure": "1 Hour", "armRegionName": "eastus", "type": "Consumption",
             "productName": "Virtual Machines Dsv5 Series"},
            # Spot variant — excluded by skuName != armSkuName.
            {"armSkuName": "Standard_D4s_v5", "skuName": "Standard_D4s_v5 Spot", "retailPrice": 0.040,
             "unitOfMeasure": "1 Hour", "armRegionName": "eastus", "type": "Consumption",
             "productName": "Virtual Machines Dsv5 Series"},
            # Windows row — excluded by productName.
            {"armSkuName": "Standard_D4s_v5", "skuName": "Standard_D4s_v5", "retailPrice": 0.376,
             "unitOfMeasure": "1 Hour", "armRegionName": "eastus", "type": "Consumption",
             "productName": "Virtual Machines Dsv5 Series Windows"},
            # Unknown SKU (not in specs CSV) — skipped.
            {"armSkuName": "Unknown_Sku_X", "skuName": "Unknown_Sku_X", "retailPrice": 0.5,
             "unitOfMeasure": "1 Hour", "armRegionName": "eastus", "type": "Consumption",
             "productName": "Virtual Machines X"},
        ],
        "NextPageLink": None,
    }


def _responder():
    def respond(url, params, headers):
        if "pricing.us-east-1.amazonaws.com" in url:
            return FakeResponse(json_body=_aws_body())
        if "$skip=100" in url:
            return FakeResponse(json_body=_azure_page_two())
        if "prices.azure.com" in url:
            return FakeResponse(json_body=_azure_page_one())
        return FakeResponse(json_body={})

    return respond


def _fake_http():
    return RecordingSession(_responder())


def test_adapter_is_registered():
    assert "cloud-price-list" in SOURCE_REGISTRY


def test_aws_parsing_filters_and_prices():
    session = RecordingSession(_responder())
    source = SOURCE_REGISTRY["cloud-price-list"](
        providers=[{"name": "aws", "region": "us-east-1"}]
    )
    rows = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    types = {r["instance_type"]: r for r in rows}
    assert set(types) == {"m5.large", "m5.xlarge"}  # Windows + Dedicated dropped
    assert types["m5.large"]["usd_per_hour"] == 0.096
    assert types["m5.large"]["vcpu"] == 2.0
    assert types["m5.large"]["memory_gib"] == 8.0


def test_azure_paging_and_specs_enrichment():
    session = RecordingSession(_responder())
    source = SOURCE_REGISTRY["cloud-price-list"](
        providers=[{"name": "azure", "region": "eastus"}]
    )
    rows = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    # two pages fetched; zero-price + unknown-spec SKUs dropped
    assert len(session.calls) == 2
    skus = {r["instance_type"]: r for r in rows}
    assert set(skus) == {"Standard_D2s_v5", "Standard_D4s_v5"}
    assert skus["Standard_D2s_v5"]["vcpu"] == 2.0
    assert skus["Standard_D2s_v5"]["memory_gib"] == 8.0
    # On-demand PAYG price wins; Spot / Low-Priority / Windows rows are excluded.
    assert skus["Standard_D2s_v5"]["usd_per_hour"] == 0.096
    assert skus["Standard_D4s_v5"]["usd_per_hour"] == 0.192


def test_validate_passes(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    assert sdk.validate("hosting-cloud-pricing").slug == "hosting-cloud-pricing"


def test_end_to_end_run_is_byte_stable_with_schema_columns(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    config = sdk.validate("hosting-cloud-pricing")
    columns = config.schema.column_names()

    first = sdk.run("hosting-cloud-pricing", http=_fake_http())
    first_bytes = first.read_bytes()
    second = sdk.run("hosting-cloud-pricing", http=_fake_http())

    assert first.parts[-2] == "hosting-cloud-pricing"  # output/<slug>/<ts>.csv
    assert first == second and second.read_bytes() == first_bytes

    lines = first.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == columns
    # 2 AWS + 2 Azure comparable instances
    assert len(lines) - 1 == 4


def test_priceperf_index_rewards_cheapest_per_vcpu(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    sdk.run("hosting-cloud-pricing", http=_fake_http())
    rows = sdk.dataset("hosting-cloud-pricing").latest()
    by_cost = {r["instance_type"]: float(r["usd_per_vcpu_hr"]) for r in rows}
    index = {r["instance_type"]: float(r["priceperf_index"]) for r in rows}
    cheapest = min(by_cost, key=by_cost.get)
    dearest = max(by_cost, key=by_cost.get)
    # invert=true → cheapest per vCPU gets the highest index (1.0), dearest 0.0
    assert index[cheapest] == 1.0
    assert index[dearest] == 0.0
