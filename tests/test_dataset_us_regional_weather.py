"""S06 — the first real dataset: ncei-climate adapter + end-to-end fixture run.

No SDK code is exercised beyond the two S06 additions (the adapter and the
``rolling_corr`` helper). Network is fully mocked; zero live calls.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.config.loader import load_custom_sources
from datavibes.context import FetchContext, FixedClock
from datavibes.registry import SOURCE_REGISTRY
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse

DATASET_DIR = Path(__file__).resolve().parents[1] / "datasets" / "us-regional-weather"
STATION = "USW00094728"
FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))


@pytest.fixture(autouse=True)
def _register_adapter():
    load_custom_sources(DATASET_DIR)


def _ncei_body(results, count):
    return {"metadata": {"resultset": {"offset": 1, "count": count, "limit": 1000}},
            "results": results}


def _daily_results(days):
    results = []
    for index in range(days):
        day = f"2026-05-{index + 1:02d}T00:00:00"
        results.append({"date": day, "datatype": "TMAX", "station": STATION, "value": 200 + index * 10})
        results.append({"date": day, "datatype": "TMIN", "station": STATION, "value": 100 + index * 10})
        results.append({"date": day, "datatype": "PRCP", "station": STATION, "value": 50 + index})
    return results


def test_adapter_is_registered():
    assert "ncei-climate" in SOURCE_REGISTRY


def test_adapter_sends_token_header(monkeypatch, make_session):
    monkeypatch.delenv("NCDC_WEB_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("NCEI_TOKEN", "secret-token")
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=_ncei_body([], 0))
    )
    source = SOURCE_REGISTRY["ncei-climate"](stations=[STATION])
    list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert session.calls[0]["headers"]["token"] == "secret-token"


def test_adapter_reads_canonical_ncdc_token(monkeypatch, make_session):
    monkeypatch.setenv("NCDC_WEB_SERVICE_TOKEN", "ncdc-tok")
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=_ncei_body([], 0))
    )
    source = SOURCE_REGISTRY["ncei-climate"](stations=[STATION])
    list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert session.calls[0]["headers"]["token"] == "ncdc-tok"


def test_canonical_token_wins_over_alias(monkeypatch, make_session):
    monkeypatch.setenv("NCDC_WEB_SERVICE_TOKEN", "canonical")
    monkeypatch.setenv("NCEI_TOKEN", "alias")
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=_ncei_body([], 0))
    )
    source = SOURCE_REGISTRY["ncei-climate"](stations=[STATION])
    list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert session.calls[0]["headers"]["token"] == "canonical"


def test_adapter_prefixes_bare_station_id_with_dataset(make_session):
    # CDO v2 requires stationid="GHCND:USW00094728"; config carries the bare id.
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=_ncei_body([], 0))
    )
    source = SOURCE_REGISTRY["ncei-climate"](dataset="GHCND", stations=[STATION])
    list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert session.calls[0]["params"]["stationid"] == f"GHCND:{STATION}"


def test_date_windows_split_over_one_year():
    import sys
    from datetime import date, timedelta

    mod = sys.modules[SOURCE_REGISTRY["ncei-climate"].__module__]
    windows = list(mod._date_windows(date(2025, 5, 30), date(2026, 7, 4), 365))
    # More than one window (range > 1 year); each window <= 365 inclusive days;
    # contiguous with no gap/overlap; covers the full range.
    assert len(windows) == 2
    assert all((e - s).days <= 364 for s, e in windows)
    assert windows[0][0] == date(2025, 5, 30) and windows[-1][1] == date(2026, 7, 4)
    assert windows[1][0] == windows[0][1] + timedelta(days=1)


def test_adapter_walks_all_pages(make_session):
    page_one = _daily_results(3)  # 9 records

    def responder(url, params, headers):
        if params["offset"] == 1:
            return FakeResponse(json_body=_ncei_body(page_one, count=1500))
        if params["offset"] == 1001:
            return FakeResponse(json_body=_ncei_body(_daily_results(2), count=1500))
        return FakeResponse(json_body=_ncei_body([], count=1500))

    session = make_session(responder)
    # lookback within a single CDO window so this test isolates paging.
    source = SOURCE_REGISTRY["ncei-climate"](stations=[STATION], lookback_days=30)
    records = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert len(session.calls) == 2
    assert len(records) == 9 + 6


def test_adapter_maps_results_to_schema_rows(make_session):
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=_ncei_body(_daily_results(1), count=3))
    )
    source = SOURCE_REGISTRY["ncei-climate"](stations=[STATION])
    records = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    temp_rows = [r for r in records if "temp_mean_c" in r]
    precip_rows = [r for r in records if "precip_mm" in r]
    assert temp_rows[0] == {"region": STATION, "date": "2026-05-01", "temp_mean_c": 20.0}
    assert precip_rows[0] == {"region": STATION, "date": "2026-05-01", "precip_mm": 5.0}


def test_adapter_empty_station_is_empty_not_crash(make_session):
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=_ncei_body([], count=0))
    )
    source = SOURCE_REGISTRY["ncei-climate"](stations=[STATION])
    assert list(source.fetch(FetchContext(config=None, clock=FIXED, http=session))) == []


def _fake_http(days):
    from tests.conftest import RecordingSession

    body = _ncei_body(_daily_results(days), count=days * 3)

    def responder(url, params, headers):
        if params["offset"] == 1:
            return FakeResponse(json_body=body)
        return FakeResponse(json_body=_ncei_body([], count=days * 3))

    return RecordingSession(responder)


def test_validate_passes(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    config = sdk.validate("us-regional-weather")
    assert config.slug == "us-regional-weather"


def test_end_to_end_run_is_byte_stable_with_schema_columns(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    config = sdk.validate("us-regional-weather")
    schema_columns = config.schema.column_names()

    first = sdk.run("us-regional-weather", http=_fake_http(days=10))
    first_bytes = first.read_bytes()
    second = sdk.run("us-regional-weather", http=_fake_http(days=10))

    # Path shape: output/environment/us-regional-weather-<hash>/<ts>.csv
    assert first.parts[-3] == "environment"
    assert first.parts[-2].startswith("us-regional-weather-")
    assert first.parts[-1] == "2026-06-01-00-00.csv"

    # Byte-stable under the fixed clock.
    assert first == second
    assert second.read_bytes() == first_bytes

    lines = first.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == schema_columns  # exactly the declared columns
    assert len(lines) - 1 == 10  # one row per date


def test_end_to_end_row_size_band(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    path = sdk.run("us-regional-weather", http=_fake_http(days=10))
    row_count = len(path.read_text(encoding="utf-8").splitlines()) - 1
    assert 1 <= row_count <= 400
