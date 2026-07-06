"""S10 — Vehicle Production → EV Share: iea-ev adapter + end-to-end run.

Network fully mocked. Processing is pure config on the S07 primitives
(sort / grouped cagr / grouped corr).
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

DATASET_DIR = (
    Path(__file__).resolve().parents[1] / "datasets" / "vehicle-production-ev-share"
)
FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))
YEARS = list(range(2018, 2024))  # 6 years → last row has a 5y CAGR


@pytest.fixture(autouse=True)
def _register_adapter():
    load_custom_sources(DATASET_DIR)


def _iea_records():
    records = []
    for region, base in (("Germany", 5.0), ("China", 10.0)):
        for offset, year in enumerate(YEARS):
            records.append(
                {"region": region, "mode": "Cars", "category": "Historical",
                 "parameter": "EV sales", "powertrain": "BEV", "year": year,
                 "unit": "Vehicles", "value": 100000 + offset * 20000}
            )
            records.append(
                {"region": region, "mode": "Cars", "category": "Historical",
                 "parameter": "EV sales", "powertrain": "PHEV", "year": year,
                 "unit": "Vehicles", "value": 50000 + offset * 10000}
            )
            records.append(
                {"region": region, "mode": "Cars", "category": "Historical",
                 "parameter": "EV sales share", "powertrain": "EV", "year": year,
                 "unit": "percent", "value": base + offset * 3}
            )
            records.append(
                {"region": region, "mode": "Cars", "category": "Historical",
                 "parameter": "EV charging points", "powertrain": "Publicly available",
                 "year": year, "unit": "charging points", "value": 1000 + offset * 500}
            )
    # Noise the adapter must ignore: wrong mode + unconfigured parameter.
    records.append(
        {"region": "Germany", "mode": "Buses", "category": "Historical",
         "parameter": "EV sales", "powertrain": "BEV", "year": 2023, "value": 999}
    )
    return records


def _fake_http():
    body = _iea_records()
    return RecordingSession(lambda url, params, headers: FakeResponse(json_body=body))


def test_adapter_is_registered():
    assert "iea-ev" in SOURCE_REGISTRY


def test_adapter_pivots_and_sums_powertrains():
    body = _iea_records()
    session = RecordingSession(lambda url, params, headers: FakeResponse(json_body=body))
    source = SOURCE_REGISTRY["iea-ev"](
        parameters={
            "EV sales": "ev_sales",
            "EV sales share": "ev_share_pct",
            "EV charging points": "charging_points",
        }
    )
    rows = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    germany_2018 = [r for r in rows if r["country"] == "Germany" and r["year"] == 2018][0]
    # BEV 100000 + PHEV 50000 summed into ev_sales
    assert germany_2018["ev_sales"] == 150000.0
    assert germany_2018["ev_share_pct"] == 5.0
    assert germany_2018["charging_points"] == 1000.0
    # 'Buses' mode row is ignored → no spurious inflation
    assert all(r["country"] != "Germany" or r["year"] != 2023 or r["ev_sales"] <= 500000 for r in rows)


def test_validate_passes(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    assert sdk.validate("vehicle-production-ev-share").slug == "vehicle-production-ev-share"


def test_end_to_end_run_is_byte_stable_with_schema_columns(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    config = sdk.validate("vehicle-production-ev-share")
    columns = config.schema.column_names()

    first = sdk.run("vehicle-production-ev-share", http=_fake_http())
    first_bytes = first.read_bytes()
    second = sdk.run("vehicle-production-ev-share", http=_fake_http())

    assert first.parts[-3] == "mobility"
    assert first.parts[-2].startswith("vehicle-production-ev-share-")
    assert first == second and second.read_bytes() == first_bytes

    lines = first.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == columns
    assert len(lines) - 1 == 2 * len(YEARS)


def test_cagr_and_corr_populated_per_country(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    sdk.run("vehicle-production-ev-share", http=_fake_http())
    rows = sdk.dataset("vehicle-production-ev-share").latest()
    last = [r for r in rows if r["country"] == "China" and r["year"] == "2023"][0]
    first = [r for r in rows if r["country"] == "China" and r["year"] == "2018"][0]
    assert last["ev_cagr_5y"] != ""       # 5y lag filled on the last year
    assert first["ev_cagr_5y"] == ""      # no lag on the first year
    # ev share and charging points both rise monotonically → perfect correlation
    assert abs(float(last["ev_infra_corr"]) - 1.0) < 1e-9
