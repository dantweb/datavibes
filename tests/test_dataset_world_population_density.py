"""S13 — ``worldbank-latest`` adapter + the two colored-geostats datasets end to end.

Network is fully mocked with recorded-shape World Bank bodies; zero live calls.
"""

import json
import os
import re
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.context import FetchContext
from datavibes.errors import SourceFetchError
from datavibes.registry import SOURCE_REGISTRY
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse

DATASETS = Path(__file__).resolve().parents[1] / "datasets"
GOLDEN = Path(__file__).parent / "golden"

DENSITY = "EN.POP.DNST"
FEMALE = "SP.POP.TOTL.FE.ZS"


def _obs(indicator, iso3, name, value, year):
    return {"indicator": {"id": indicator, "value": "x"}, "country": {"id": iso3[:2], "value": name},
            "countryiso3code": iso3, "date": str(year), "value": value, "obs_status": "", "decimal": 0}


DENSITY_PAGES = [
    [_obs(DENSITY, "WLD", "World", 62.1, 2024),            # aggregate → dropped
     _obs(DENSITY, "DEU", "Germany", 238.2, 2024),
     _obs(DENSITY, "RUS", "Russian Federation", 8.8, 2024),
     _obs(DENSITY, "", "Unnamed", 1.0, 2024)],              # blank code → dropped
    [_obs(DENSITY, "QAT", "Qatar", 245.4, 2024),
     _obs(DENSITY, "GRL", "Greenland", 0.14, 2024),
     _obs(DENSITY, "SSD", "South Sudan", 18.7, 2023),
     _obs(DENSITY, "MAC", "Macao SAR, China", 20630.6, 2024),  # no 110m geometry
     _obs(DENSITY, "BGD", "Bangladesh", 1301.0, 2024),      # drawn and overpopulated
     _obs(DENSITY, "XKX", "Kosovo", None, 2024)],           # null value → dropped
]
FEMALE_PAGE = [
    _obs(FEMALE, "WLD", "World", 49.7, 2025),
    _obs(FEMALE, "DEU", "Germany", 50.6, 2025),
    _obs(FEMALE, "RUS", "Russian Federation", 53.6, 2025),
    _obs(FEMALE, "QAT", "Qatar", 28.4, 2025),
    _obs(FEMALE, "GRL", "Greenland", 47.1, 2025),
    _obs(FEMALE, "SSD", "South Sudan", 50.02, 2025),
    _obs(FEMALE, "MAC", "Macao SAR, China", 53.9, 2025),
    _obs(FEMALE, "BGD", "Bangladesh", 50.4, 2025),
    _obs(FEMALE, "XKX", "Kosovo", 50.2, 2025),
]
COUNTRIES = [
    {"id": "WLD", "name": "World", "region": {"id": "NA", "value": "Aggregates"}},
    {"id": "DEU", "name": "Germany", "region": {"id": "ECS", "value": "Europe & Central Asia"}},
]


def _responder(url, params, headers):
    if url.endswith("/country"):
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, COUNTRIES])
    page = int(params.get("page", 1))
    if f"/indicator/{DENSITY}" in url:
        return FakeResponse(json_body=[{"page": page, "pages": 2}, DENSITY_PAGES[page - 1]])
    if f"/indicator/{FEMALE}" in url:
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, FEMALE_PAGE])
    raise AssertionError(f"unexpected url {url}")


def _source(**overrides):
    options = {
        "indicators": {
            DENSITY: {"value": "density_per_km2", "year": "density_year"},
            FEMALE: {"value": "female_share_pct", "year": "sex_year"},
        }
    }
    options.update(overrides)
    return SOURCE_REGISTRY["worldbank-latest"](**options)


def _fetch(session, **overrides):
    return list(_source(**overrides).fetch(FetchContext(config=None, clock=None, http=session)))


# ------------------------------------------------------------------- adapter
def test_adapter_merges_indicators_per_country_and_drops_aggregates(make_session):
    records = _fetch(make_session(_responder))
    by_code = {record["iso3"]: record for record in records}
    assert sorted(by_code) == ["BGD", "DEU", "GRL", "MAC", "QAT", "RUS", "SSD", "XKX"]
    assert by_code["DEU"] == {"iso3": "DEU", "country": "Germany", "density_per_km2": 238.2,
                              "density_year": 2024, "female_share_pct": 50.6, "sex_year": 2025}
    assert by_code["SSD"]["density_year"] == 2023


def test_adapter_emits_every_mapped_column_even_when_missing(make_session):
    kosovo = {record["iso3"]: record for record in _fetch(make_session(_responder))}["XKX"]
    assert kosovo["density_per_km2"] is None and kosovo["density_year"] is None
    assert kosovo["female_share_pct"] == 50.2


def test_adapter_walks_every_page_and_sends_mrnev(make_session):
    session = make_session(_responder)
    _fetch(session)
    density_calls = [call for call in session.calls if DENSITY in call["url"]]
    assert [call["params"]["page"] for call in density_calls] == [1, 2]
    assert all(call["params"]["mrnev"] == 1 and call["params"]["format"] == "json" for call in density_calls)


def test_adapter_can_keep_aggregates(make_session):
    session = make_session(_responder)
    records = _fetch(session, exclude_aggregates=False)
    assert "WLD" in {record["iso3"] for record in records}
    assert not any(call["url"].endswith("/country") for call in session.calls)


def test_adapter_raises_typed_error_on_api_error_body(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(
        json_body=[{"message": [{"id": "120", "value": "Invalid value"}]}]))
    with pytest.raises(SourceFetchError):
        _fetch(session)


# ---------------------------------------------------------------- end to end
def _sdk(tmp_path, fixed_clock, name):
    return DatasetSDK(root=DATASETS, clock=fixed_clock, store=FileStore(tmp_path / name),
                      env_file=tmp_path / "none.env", config_file=tmp_path / "none.yaml")


def _assert_golden(path: Path, name: str):
    golden = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_bytes(path.read_bytes())
    assert path.read_bytes() == golden.read_bytes(), f"{name} drifted (UPDATE_GOLDEN=1 to accept)"


@pytest.mark.parametrize("slug", ["world-population-density", "world-population-density-heat"])
def test_dataset_validates(tmp_path, fixed_clock, slug):
    config = _sdk(tmp_path, fixed_clock, "v").validate(slug)
    assert config.category == "colored-geostats"
    assert [spec.name for spec in config.outputs] == ["csv", "svg-map"]


def test_bivariate_run_writes_csv_svg_and_join_report_byte_stably(tmp_path, fixed_clock, make_session):
    first = _sdk(tmp_path, fixed_clock, "a").run_outputs("world-population-density", http=make_session(_responder))
    second = _sdk(tmp_path, fixed_clock, "b").run_outputs("world-population-density", http=make_session(_responder))
    assert [path.name for path in first] == ["2026-06-01-00-00.csv", "2026-06-01-00-00.svg"]
    assert first[0].parent.name == "world-population-density"  # default "slug" output layout
    for one, two in zip(first, second):
        assert one.read_bytes() == two.read_bytes()
    _assert_golden(first[0], "world_population_density.csv")

    svg = first[1].read_text(encoding="utf-8")
    assert len(re.findall(r"<path id=", svg)) == 176  # 177 Natural Earth countries minus Antarctica
    blue = re.search(r'<path id="QAT" fill="(#[0-9a-f]{6})"', svg).group(1)   # far more men
    red = re.search(r'<path id="RUS" fill="(#[0-9a-f]{6})"', svg).group(1)    # more women
    assert int(blue[5:7], 16) > int(blue[1:3], 16)   # blue channel dominates
    assert int(red[1:3], 16) > int(red[5:7], 16)     # red channel dominates
    assert re.search(r'<path id="SDS" fill="#9e9e9e"', svg)  # SSD aliased; ≈ equal sex ratio

    report = json.loads(first[1].with_suffix(".join.json").read_text(encoding="utf-8"))
    assert report["rows_not_drawn"] == ["MAC"]               # micro-state, no 110m shape
    assert "KOS" in report["features_with_missing_values"]   # aliased, but no density
    assert "ATA" not in report["features_without_rows"]      # excluded from the map
    assert "Countries coloured: " in svg and "Without data (grey): " in svg
    assert "In the data but not drawn (too small at this scale or outside the map): 1" in svg


def test_csv_columns_and_derived_values(tmp_path, fixed_clock, make_session):
    sdk = _sdk(tmp_path, fixed_clock, "c")
    sdk.run_outputs("world-population-density", http=make_session(_responder))
    rows = {row["iso3"]: row for row in sdk.latest_rows("world-population-density")}
    assert rows["QAT"]["male_share_pct"] == "71.6" and rows["QAT"]["majority"] == "male"
    assert rows["RUS"]["majority"] == "female"
    assert rows["SSD"]["majority"] == "equal"
    assert rows["GRL"]["density_saturation"] == "0.1" and rows["MAC"]["density_saturation"] == "1.0"
    assert rows["XKX"]["density_saturation"] == ""
    assert rows["BGD"]["overpopulated"] == "True" and rows["MAC"]["overpopulated"] == "True"
    assert rows["DEU"]["overpopulated"] == "False" and rows["XKX"]["overpopulated"] == ""


def _fill(svg: str, key: str) -> str:
    return re.search(rf'<path id="{key}" fill="(#[0-9a-f]{{6}})"', svg).group(1)


def test_heat_map_paints_overpopulated_countries_red(tmp_path, fixed_clock, make_session):
    paths = _sdk(tmp_path, fixed_clock, "h").run_outputs("world-population-density-heat", http=make_session(_responder))
    svg = paths[1].read_text(encoding="utf-8")
    assert _fill(svg, "BGD") == "#d7191c"          # 1,301/km² ≥ 1,000 → red
    assert _fill(svg, "DEU") != "#d7191c"          # 238/km² → not red
    assert "≥ 1,000" in svg


def test_threshold_can_be_overridden_from_the_environment(tmp_path, fixed_clock, make_session, monkeypatch):
    monkeypatch.setenv("OVERPOPULATED_PER_KM2", "200")
    sdk = _sdk(tmp_path, fixed_clock, "o")
    paths = sdk.run_outputs("world-population-density-heat", http=make_session(_responder))
    rows = {row["iso3"]: row for row in sdk.latest_rows("world-population-density-heat")}
    assert rows["DEU"]["overpopulated"] == "True"
    svg = paths[1].read_text(encoding="utf-8")
    assert _fill(svg, "DEU") == _fill(svg, "QAT") == "#d7191c"
    assert "≥ 200" in svg


def test_bivariate_map_tints_from_white(tmp_path, fixed_clock, make_session):
    paths = _sdk(tmp_path, fixed_clock, "w").run_outputs("world-population-density", http=make_session(_responder))
    svg = paths[1].read_text(encoding="utf-8")
    greenland = _fill(svg, "GRL")                  # sparsest, more men → almost white with a blue tint
    red, green, blue = (int(greenland[i:i + 2], 16) for i in (1, 3, 5))
    assert min(red, green, blue) > 200 and blue == 255
    assert 'fill="#e9eef3"' in svg                 # ocean background


def test_spectral_variant_shares_the_csv_and_differs_only_in_the_map(tmp_path, fixed_clock, make_session):
    bivariate = _sdk(tmp_path, fixed_clock, "bi").run_outputs("world-population-density", http=make_session(_responder))
    spectral = _sdk(tmp_path, fixed_clock, "sp").run_outputs("world-population-density-heat", http=make_session(_responder))
    assert bivariate[0].read_bytes() == spectral[0].read_bytes()
    svg = spectral[1].read_text(encoding="utf-8")
    assert re.search(r'<path id="GRL" fill="#08306b"', svg)   # lowest → dark blue
    assert "green = average" in svg
