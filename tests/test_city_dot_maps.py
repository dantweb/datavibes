"""S14 — city dot maps: ``sparql`` source, ``lookup`` step, ``svg-dot-map`` writer, datasets.

Network is fully mocked; zero live calls.
"""

import json
import os
import re
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.context import FetchContext, RunContext
from datavibes.errors import ConfigError, SourceFetchError
from datavibes.processing import functions
from datavibes.processing.steps import DERIVE_FUNCTIONS
from datavibes.registry import SOURCE_REGISTRY, resolve_step, resolve_writer
from datavibes.config.models import StepSpec
from datavibes.schema.field import Field, Schema
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse

DATASETS = Path(__file__).resolve().parents[1] / "datasets"
FIXTURES = Path(__file__).parent / "fixtures" / "geometry"
GOLDEN = Path(__file__).parent / "golden"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _assert_golden(path: Path, name: str):
    golden = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_bytes(path.read_bytes())
    assert path.read_bytes() == golden.read_bytes(), f"{name} drifted (UPDATE_GOLDEN=1 to accept)"


def _literal(value, datatype=None):
    cell = {"type": "literal", "value": str(value)}
    if datatype:
        cell["datatype"] = XSD + datatype
    return cell


def _city(qid, name, iso3, population, lat, lon, area=None):
    row = {
        "city": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"},
        "cityLabel": {"type": "literal", "xml:lang": "en", "value": name},
        "iso3": _literal(iso3),
        "population": _literal(population, "decimal"),
        "latitude": _literal(lat, "double"),
        "longitude": _literal(lon, "double"),
    }
    if area is not None:
        row["area_km2"] = _literal(area, "decimal")
    return row


SPARQL_BODY = {
    "head": {"vars": ["city", "cityLabel", "iso3", "population", "latitude", "longitude", "area_km2"]},
    "results": {"bindings": [
        _city("Q1", "Moscow", "RUS", 13010112, 55.75, 37.62, 2561.5),     # women majority, ~5,079/km²
        _city("Q2", "Doha", "QAT", 1186023, 25.29, 51.53, 132.1),         # men majority, ~8,978/km²
        _city("Q3", "Dhaka", "BGD", 10278882, 23.76, 90.39, 306.4),       # ~33,547/km² → overpopulated
        _city("Q4", "Berlin", "DEU", 3755251, 52.52, 13.40, 891.1),       # ~4,214/km²
        _city("Q5", "Nowhere City", "DEU", 150000, 50.0, 10.0),           # no area → no density
        _city("Q6", "Bad Area", "RUS", 200000, 54.7, 20.5, 0.01),         # implausible density → nulled
        _city("Q7", "Taipei", "TWN", 2500000, 25.03, 121.56, 271.8),      # density, but no World Bank sex ratio
    ]},
}


def _sparql_fixture_responder(url, params, headers):
    if "query.wikidata.org" in url:
        return FakeResponse(json_body=SPARQL_BODY)
    if url.endswith("/country"):
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, [
            {"id": "WLD", "name": "World", "region": {"value": "Aggregates"}}]])
    observations = [
        ("RUS", "Russian Federation", 53.6), ("QAT", "Qatar", 28.4),
        ("BGD", "Bangladesh", 50.4), ("DEU", "Germany", 50.6), ("WLD", "World", 49.7),
    ]
    return FakeResponse(json_body=[{"page": 1, "pages": 1}, [
        {"countryiso3code": iso3, "country": {"value": name}, "date": "2025", "value": value}
        for iso3, name, value in observations
    ]])


# ------------------------------------------------------------------ sparql source
def _fetch(session, **options):
    options.setdefault("query", "SELECT * WHERE { ?s ?p ?o }")
    source = SOURCE_REGISTRY["sparql"](**options)
    return list(source.fetch(FetchContext(config=None, clock=None, http=session)))


def test_sparql_flattens_bindings_and_casts_typed_literals(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body=SPARQL_BODY))
    records = _fetch(session, strip_uri_prefix=True)
    assert records[0] == {"city": "Q1", "cityLabel": "Moscow", "iso3": "RUS", "population": 13010112.0,
                          "latitude": 55.75, "longitude": 37.62, "area_km2": 2561.5}
    assert "area_km2" not in records[4] or records[4]["area_km2"] is None


def test_sparql_emits_every_head_var_even_when_unbound(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body=SPARQL_BODY))
    assert _fetch(session)[4]["area_km2"] is None


def test_sparql_sends_query_and_json_accept_header(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body=SPARQL_BODY))
    _fetch(session, query="SELECT ?x WHERE {}")
    call = session.calls[0]
    assert call["url"] == "https://query.wikidata.org/sparql"
    assert call["params"]["query"] == "SELECT ?x WHERE {}"
    assert call["headers"]["Accept"] == "application/sparql-results+json"


def test_sparql_uses_its_own_longer_timeout(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body=SPARQL_BODY))
    _fetch(session)
    assert session.calls[0]["timeout"] == 90.0
    _fetch(session, timeout_seconds=120)
    assert session.calls[1]["timeout"] == 120.0


def test_sparql_rejects_a_body_without_results(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body={"error": "x"}))
    with pytest.raises(SourceFetchError):
        _fetch(session)


def test_sparql_requires_a_query():
    with pytest.raises(ConfigError):
        SOURCE_REGISTRY["sparql"](query="")


# -------------------------------------------------------------------- lookup step
def _lookup(**options):
    return resolve_step(StepSpec(name="lookup", options=options))


def test_lookup_copies_columns_by_key_and_drops_the_lookup_rows():
    rows = [
        {"iso3": "RUS", "city": "Moscow", "_source": "sparql#0"},
        {"iso3": "XXX", "city": "Atlantis", "_source": "sparql#0"},
        {"iso3": "RUS", "female_share_pct": 53.6, "country": "Russia", "_source": "worldbank-latest#1"},
    ]
    result = _lookup(from_source="worldbank-latest", on="iso3",
                     columns={"female_share_pct": "country_female_share_pct", "country": "country"}).apply(
        rows, RunContext(config=None, clock=None))
    assert result == [
        {"iso3": "RUS", "city": "Moscow", "_source": "sparql#0", "country_female_share_pct": 53.6, "country": "Russia"},
        {"iso3": "XXX", "city": "Atlantis", "_source": "sparql#0", "country_female_share_pct": None, "country": None},
    ]


def test_lookup_validates_options():
    with pytest.raises(ConfigError):
        _lookup(on="iso3", columns={"a": "b"})
    with pytest.raises(ConfigError):
        _lookup(from_source="x", on="iso3", columns={})


# ----------------------------------------------------------------- helper
def test_null_outside_drops_implausible_values():
    assert functions.null_outside([5.0, 10.0, 500.0, 60000.0, 70000.0, None], low=10, high=60000) == [
        None, 10.0, 500.0, 60000.0, None, None]
    assert "null_outside" in DERIVE_FUNCTIONS


# ------------------------------------------------------------- svg-dot-map writer
SCHEMA = Schema([Field(name="name"), Field(name="lat", dtype="float"), Field(name="lon", dtype="float"),
                 Field(name="population", dtype="int"), Field(name="density", dtype="float", nullable=True),
                 Field(name="male", dtype="float", nullable=True)])
DOTS = [
    {"name": "Small", "lat": 45.0, "lon": 5.0, "population": 100000, "density": 100.0, "male": 52.0},
    {"name": "Big & <Co>", "lat": 10.0, "lon": 10.0, "population": 10000000, "density": 10000.0, "male": 48.0},
    {"name": "Mid", "lat": 25.0, "lon": 65.0, "population": 1000000, "density": None, "male": 51.0},
    {"name": "Lost", "lat": None, "lon": None, "population": 500000, "density": 50.0, "male": 50.0},
]


def _dot_writer(**overrides):
    options = {
        "geometry": "fixture-countries",
        "geometry_manifest": str(FIXTURES / "manifest.yaml"),
        "latitude_column": "lat",
        "longitude_column": "lon",
        "size_column": "population",
        "label_columns": ["name", "population"],
        "title": "Fixture cities",
        "color_scale": {"type": "sex-ratio-bivariate", "ratio_column": "male", "value_column": "density",
                        "ratio_label": "sex majority (country level)"},
    }
    options.update(overrides)
    return resolve_writer("svg-dot-map", options)


def _circles(svg: str) -> list[tuple[float, str]]:
    return [(float(radius), fill) for radius, fill in
            re.findall(r'<circle cx="[^"]+" cy="[^"]+" r="([^"]+)" fill="(#[0-9a-f]{6})"', svg)]


def test_dot_map_matches_golden_and_is_byte_stable(tmp_path):
    first = _dot_writer().write(DOTS, SCHEMA, tmp_path / "a" / "2026-06-01-00-00.svg")
    second = _dot_writer().write(DOTS, SCHEMA, tmp_path / "b" / "2026-06-01-00-00.svg")
    assert first.read_bytes() == second.read_bytes()
    _assert_golden(first, "fixture_dots.svg")


def test_dot_area_is_proportional_to_size_and_big_dots_draw_first(tmp_path):
    svg = _dot_writer(min_radius=0.5, max_radius=20).write(DOTS, SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8")
    circles = _circles(svg)
    radii = [radius for radius, _ in circles]
    assert radii == sorted(radii, reverse=True)       # small dots stay visible on top
    assert radii[0] == pytest.approx(20.0)            # 10M → max radius
    assert radii[1] == pytest.approx(20.0 * (0.1 ** 0.5), abs=0.06)  # 1M → √(1/10) of max
    assert radii[2] == pytest.approx(20.0 * (0.01 ** 0.5), abs=0.06)


def test_dot_without_colour_value_is_no_data_and_without_coordinates_is_skipped(tmp_path):
    dest = _dot_writer().write(DOTS, SCHEMA, tmp_path / "2026-06-01-00-00.svg")
    svg = dest.read_text(encoding="utf-8")
    circles = _circles(svg)
    assert len(circles) == 3
    assert ("#d9d9d9" in [fill for _, fill in circles])   # "Mid" has no density
    assert "No data" in svg                                # …so the legend explains the grey dot
    report = json.loads((tmp_path / "2026-06-01-00-00.join.json").read_text(encoding="utf-8"))
    assert report == {"drawn_points": 3, "points_without_color": 1, "rows_without_coordinates": 1,
                      "geometry": "fixture-countries", "scope": "world"}


def test_dot_map_draws_countries_as_a_neutral_basemap(tmp_path):
    svg = _dot_writer().write(DOTS, SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8")
    assert set(re.findall(r'<path id="[A-Z]+" fill="(#[0-9a-f]{6})"', svg)) == {"#e3e6ea"}
    assert "sex majority (country level)" in svg
    assert "Big &amp; &lt;Co&gt;" in svg
    for label in ("100,000", "1,000,000", "10,000,000"):  # size legend
        assert label in svg


def test_dot_map_rejects_bad_radius_range():
    with pytest.raises(ConfigError):
        _dot_writer(min_radius=5, max_radius=2)


# ------------------------------------------------------------------ end to end
def _sdk(tmp_path, fixed_clock, name):
    return DatasetSDK(root=DATASETS, clock=fixed_clock, store=FileStore(tmp_path / name),
                      env_file=tmp_path / "none.env", config_file=tmp_path / "none.yaml")


@pytest.mark.parametrize("slug", ["world-city-population-density", "world-city-population-density-heat"])
def test_city_datasets_validate(tmp_path, fixed_clock, slug):
    config = _sdk(tmp_path, fixed_clock, "v").validate(slug)
    assert config.category == "colored-geostats"
    assert [spec.name for spec in config.outputs] == ["csv", "svg-dot-map"]


def test_city_bivariate_run(tmp_path, fixed_clock, make_session):
    first = _sdk(tmp_path, fixed_clock, "a").run_outputs("world-city-population-density", http=make_session(_sparql_fixture_responder))
    second = _sdk(tmp_path, fixed_clock, "b").run_outputs("world-city-population-density", http=make_session(_sparql_fixture_responder))
    for one, two in zip(first, second):
        assert one.read_bytes() == two.read_bytes()
    _assert_golden(first[0], "world_city_population_density.csv")

    sdk = _sdk(tmp_path, fixed_clock, "a")
    rows = {row["city"]: row for row in sdk.latest_rows("world-city-population-density")}
    assert rows["Moscow"]["country_majority"] == "female" and rows["Doha"]["country_majority"] == "male"
    assert rows["Dhaka"]["overpopulated"] == "True" and rows["Berlin"]["overpopulated"] == "False"
    assert rows["Doha"]["country"] == "Qatar"
    # Cities that can't be coloured are excluded: no/implausible density, no country sex ratio.
    assert sorted(rows) == ["Berlin", "Dhaka", "Doha", "Moscow"]

    svg = first[1].read_text(encoding="utf-8")
    assert len(_circles(svg)) == 4
    assert "#d9d9d9" not in [fill for _, fill in _circles(svg)]
    assert "No data" not in svg  # nothing on the map lacks a colour
    assert "Cities shown: 4 of 7" in svg
    assert ("Not included: 3 — no usable density (missing or implausible area): 2 · "
            "no country sex-ratio data: 1") in svg


def test_city_heat_run_paints_dense_cities_red(tmp_path, fixed_clock, make_session):
    sdk = _sdk(tmp_path, fixed_clock, "h")
    paths = sdk.run_outputs("world-city-population-density-heat", http=make_session(_sparql_fixture_responder))
    # The heat map only needs a density: Taipei stays even without World Bank data.
    assert sorted(row["city"] for row in sdk.latest_rows("world-city-population-density-heat")) == [
        "Berlin", "Dhaka", "Doha", "Moscow", "Taipei"]
    svg = paths[1].read_text(encoding="utf-8")
    assert len(_circles(svg)) == 5 and "No data" not in svg
    assert "Cities shown: 5 of 7" in svg
    assert "Not included: 2 — no usable density (missing or implausible area): 2" in svg
    dhaka = re.search(r'<circle [^>]*fill="(#[0-9a-f]{6})"[^>]*><title>Dhaka', svg).group(1)
    assert dhaka == "#d7191c"
    assert "≥ 10,000" in svg


def test_city_min_population_reaches_the_query(tmp_path, fixed_clock, make_session, monkeypatch):
    monkeypatch.setenv("CITY_MIN_POPULATION", "250000")
    session = make_session(_sparql_fixture_responder)
    _sdk(tmp_path, fixed_clock, "q").run_outputs("world-city-population-density", http=session)
    query = next(call["params"]["query"] for call in session.calls if "wikidata" in call["url"])
    assert ">= 250000" in query
