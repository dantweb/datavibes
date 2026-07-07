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


METRICS = [
    {"parameter": "EV sales", "column": "ev_sales", "mode": "Cars", "powertrains": ["BEV", "PHEV", "FCEV"]},
    {"parameter": "EV sales share", "column": "ev_share_pct", "mode": "Cars", "powertrains": ["EV"]},
    {"parameter": "EV charging points", "column": "charging_points", "mode": "EVSE"},
]


def _records_for_year(year):
    """One IEA year-response: all regions, real mode/powertrain layout + noise."""
    offset = year - 2013
    records = []
    for region, base in (("Germany", 5.0), ("China", 10.0)):
        # EV sales split across physical powertrains under mode Cars.
        records.append({"region": region, "mode": "Cars", "parameter": "EV sales",
                        "powertrain": "BEV", "year": year, "value": 100000 + offset * 20000})
        records.append({"region": region, "mode": "Cars", "parameter": "EV sales",
                        "powertrain": "PHEV", "year": year, "value": 50000 + offset * 10000})
        # Share: single combined 'EV' powertrain under mode Cars (a percent — not summed).
        records.append({"region": region, "mode": "Cars", "parameter": "EV sales share",
                        "powertrain": "EV", "year": year, "value": base + offset * 3})
        # Charging points: mode EVSE, summed across publicly-available powertrains.
        records.append({"region": region, "mode": "EVSE", "parameter": "EV charging points",
                        "powertrain": "Publicly available fast", "year": year, "value": 600 + offset * 300})
        records.append({"region": region, "mode": "EVSE", "parameter": "EV charging points",
                        "powertrain": "Publicly available slow", "year": year, "value": 400 + offset * 200})
        # Noise the adapter must ignore: EV sales in a non-Cars mode.
        records.append({"region": region, "mode": "Trucks", "parameter": "EV sales",
                        "powertrain": "BEV", "year": year, "value": 999})
    return records


def _responder():
    def respond(url, params, headers):
        return FakeResponse(json_body=_records_for_year(params["year"]))

    return respond


def _fake_http():
    return RecordingSession(_responder())


def test_adapter_is_registered():
    assert "iea-ev" in SOURCE_REGISTRY


def test_adapter_pivots_sums_powertrains_and_pins_mode():
    session = RecordingSession(_responder())
    source = SOURCE_REGISTRY["iea-ev"](metrics=METRICS, years=[2013])  # offset 0
    rows = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    germany = [r for r in rows if r["country"] == "Germany" and r["year"] == 2013][0]
    # EV sales = BEV 100000 + PHEV 50000; the mode=Trucks row (999) is excluded.
    assert germany["ev_sales"] == 150000.0
    assert germany["ev_share_pct"] == 5.0  # single 'EV' powertrain, not summed
    assert germany["charging_points"] == 1000.0  # 600 fast + 400 slow


def test_adapter_fetches_once_per_year():
    session = RecordingSession(_responder())
    source = SOURCE_REGISTRY["iea-ev"](metrics=METRICS, years=[2018, 2019, 2020])
    list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert len(session.calls) == 3
    assert [c["params"]["year"] for c in session.calls] == [2018, 2019, 2020]


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

    assert first.parts[-2] == "vehicle-production-ev-share"  # output/<slug>/<ts>.csv
    assert first == second and second.read_bytes() == first_bytes

    lines = first.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == columns
    config_years = config.sources[0].options["years"]
    assert len(lines) - 1 == 2 * len(config_years)  # 2 countries × configured years


def test_cagr_and_corr_populated_per_country(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    sdk.run("vehicle-production-ev-share", http=_fake_http())
    rows = sdk.dataset("vehicle-production-ev-share").latest()
    last = [r for r in rows if r["country"] == "China" and r["year"] == "2024"][0]
    first = [r for r in rows if r["country"] == "China" and r["year"] == "2013"][0]
    assert last["ev_cagr_5y"] != ""       # 5y lag filled on the last year
    assert first["ev_cagr_5y"] == ""      # no lag on the first (earliest) year
    # ev share and charging points both rise monotonically → perfect correlation
    assert abs(float(last["ev_infra_corr"]) - 1.0) < 1e-9
