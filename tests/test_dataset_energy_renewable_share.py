"""S09 — Energy → Renewable Share: worldbank-indicator adapter + end-to-end run.

Network fully mocked; zero live calls. Processing is pure config on the S07
primitives (join / grouped cagr / score).
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

DATASET_DIR = Path(__file__).resolve().parents[1] / "datasets" / "energy-renewable-share"
FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))

ELEC = "EG.ELC.RNEW.ZS"
FEC = "EG.FEC.RNEW.ZS"
YEARS = list(range(2018, 2024))  # 6 years → last row has a 5y CAGR


@pytest.fixture(autouse=True)
def _register_adapter():
    load_custom_sources(DATASET_DIR)


def _wb_envelope(records, pages=1):
    return [{"page": 1, "pages": pages, "per_page": 20000, "total": len(records)}, records]


def _wb_records(column_series):
    # column_series: {iso3: (country_name, {year: value})}
    records = []
    for iso3, (name, by_year) in column_series.items():
        for year, value in by_year.items():
            records.append(
                {
                    "countryiso3code": iso3,
                    "country": {"id": iso3, "value": name},
                    "date": str(year),
                    "value": value,
                }
            )
    return records


def _responder():
    elec = _wb_records(
        {
            "DEU": ("Germany", {y: 30.0 + (y - 2018) * 5 for y in YEARS}),
            "FRA": ("France", {y: 20.0 + (y - 2018) * 2 for y in YEARS}),
        }
    )
    fec = _wb_records(
        {
            "DEU": ("Germany", {y: 15.0 + (y - 2018) for y in YEARS}),
            "FRA": ("France", {y: 11.0 + (y - 2018) for y in YEARS}),
        }
    )

    def respond(url, params, headers):
        if ELEC in url:
            return FakeResponse(json_body=_wb_envelope(elec))
        if FEC in url:
            return FakeResponse(json_body=_wb_envelope(fec))
        return FakeResponse(json_body=_wb_envelope([]))

    return respond


def _fake_http():
    return RecordingSession(_responder())


def test_adapter_is_registered():
    assert "worldbank-indicator" in SOURCE_REGISTRY


def test_adapter_maps_nested_country_and_skips_null(make_session):
    body = _wb_envelope(
        [
            {"countryiso3code": "DEU", "country": {"value": "Germany"}, "date": "2023", "value": 51.6},
            {"countryiso3code": "", "country": {"value": "World"}, "date": "2023", "value": 30.0},
            {"countryiso3code": "FRA", "country": {"value": "France"}, "date": "2023", "value": None},
        ]
    )
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = SOURCE_REGISTRY["worldbank-indicator"](
        indicators={ELEC: "renewable_elec_pct"}
    )
    rows = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert rows == [
        {"country": "Germany", "iso3": "DEU", "year": "2023", "renewable_elec_pct": 51.6}
    ]


def test_adapter_walks_pages(make_session):
    page_one = _wb_envelope(
        [{"countryiso3code": "DEU", "country": {"value": "Germany"}, "date": "2022", "value": 40.0}],
        pages=2,
    )
    page_two = _wb_envelope(
        [{"countryiso3code": "DEU", "country": {"value": "Germany"}, "date": "2023", "value": 45.0}],
        pages=2,
    )

    def respond(url, params, headers):
        return FakeResponse(json_body=page_one if params["page"] == 1 else page_two)

    session = make_session(respond)
    source = SOURCE_REGISTRY["worldbank-indicator"](indicators={ELEC: "renewable_elec_pct"})
    rows = list(source.fetch(FetchContext(config=None, clock=FIXED, http=session)))
    assert len(session.calls) == 2
    assert [r["year"] for r in rows] == ["2022", "2023"]


def test_validate_passes(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    assert sdk.validate("energy-renewable-share").slug == "energy-renewable-share"


def test_end_to_end_run_is_byte_stable_with_schema_columns(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    config = sdk.validate("energy-renewable-share")
    columns = config.schema.column_names()

    first = sdk.run("energy-renewable-share", http=_fake_http())
    first_bytes = first.read_bytes()
    second = sdk.run("energy-renewable-share", http=_fake_http())

    assert first.parts[-3] == "energy"
    assert first.parts[-2].startswith("energy-renewable-share-")
    assert first.parts[-1] == "2026-06-01-00-00.csv"
    assert first == second and second.read_bytes() == first_bytes

    lines = first.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == columns
    # one row per (country, year): 2 countries × 6 years
    assert len(lines) - 1 == 2 * len(YEARS)


def test_cagr_and_score_are_populated_on_last_year(tmp_path):
    sdk = DatasetSDK(root=DATASET_DIR.parent, clock=FIXED, store=FileStore(tmp_path))
    sdk.run("energy-renewable-share", http=_fake_http())
    rows = sdk.dataset("energy-renewable-share").latest()
    last_deu = [r for r in rows if r["iso3"] == "DEU" and r["year"] == "2023"][0]
    first_deu = [r for r in rows if r["iso3"] == "DEU" and r["year"] == "2018"][0]
    assert last_deu["renewable_cagr_5y"] != ""  # 5y lag filled
    assert first_deu["renewable_cagr_5y"] == ""  # no lag yet
    assert last_deu["transition_score"] != ""
