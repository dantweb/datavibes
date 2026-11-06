"""S13 — vendored geometry catalog, scope selection, and projections (pure)."""

import math
from pathlib import Path

import pytest

from datavibes.errors import ConfigError, DatavibesError
from datavibes.maps.geometry import GeometryCatalog, bounds, select_features
from datavibes.maps.projection import equal_earth, equirectangular, resolve_projection

FIXTURE_MANIFEST = Path(__file__).parent / "fixtures" / "geometry" / "manifest.yaml"


@pytest.fixture
def catalog():
    return GeometryCatalog(FIXTURE_MANIFEST)


# --------------------------------------------------------------------- catalog
def test_load_features_with_keys_names_and_rings(catalog):
    features = catalog.load("fixture-countries")
    assert [feature.key for feature in features] == ["AAA", "BBB", "CCC", "DDD"]
    gamma = features[2]
    assert gamma.name == "Gamma & <Co>"
    assert len(gamma.polygons) == 1 and len(gamma.polygons[0]) == 2  # outer ring + hole
    assert len(features[3].polygons) == 2  # MultiPolygon


def test_checksum_mismatch_names_the_file(catalog):
    with pytest.raises(DatavibesError) as info:
        catalog.load("broken-checksum")
    assert "countries.geojson" in str(info.value)


def test_unknown_geometry_lists_known_names(catalog):
    with pytest.raises(ConfigError) as info:
        catalog.entry("atlantis")
    assert "fixture-countries" in str(info.value)


def test_vendored_natural_earth_loads_and_verifies():
    catalog = GeometryCatalog()
    features = catalog.load("natural-earth-admin0-110m")
    keys = {feature.key for feature in features}
    assert len(features) == 177
    assert {"DEU", "USA", "BRA", "SDS", "KOS"} <= keys
    assert catalog.entry("natural-earth-admin0-110m").attribution == "Made with Natural Earth"


# -------------------------------------------------------------------- scoping
def test_world_scope_honours_exclude(catalog):
    entry = catalog.entry("fixture-countries")
    features = catalog.load("fixture-countries")
    selected = select_features(features, entry, scope="world", exclude=["DDD"])
    assert [feature.key for feature in selected] == ["AAA", "BBB", "CCC"]


def test_region_scope_by_continent_and_by_iso3(catalog):
    entry = catalog.entry("fixture-countries")
    features = catalog.load("fixture-countries")
    by_continent = select_features(features, entry, scope="region", region={"continent": "Europe"})
    assert [feature.key for feature in by_continent] == ["AAA", "BBB"]
    by_codes = select_features(features, entry, scope="region", region={"iso3": ["CCC", "DDD"]})
    assert [feature.key for feature in by_codes] == ["CCC", "DDD"]


def test_region_scope_requires_a_filter(catalog):
    entry = catalog.entry("fixture-countries")
    with pytest.raises(ConfigError):
        select_features(catalog.load("fixture-countries"), entry, scope="region", region={})


def test_country_scope_selects_admin1_subdivisions(catalog):
    entry = catalog.entry("fixture-admin1")
    selected = select_features(catalog.load("fixture-admin1"), entry, scope="country", country="AAA")
    assert [feature.key for feature in selected] == ["AAA-1", "AAA-2"]


def test_country_scope_needs_admin1_geometry(catalog):
    entry = catalog.entry("fixture-countries")
    with pytest.raises(ConfigError):
        select_features(catalog.load("fixture-countries"), entry, scope="country", country="AAA")


def test_unknown_scope_rejected(catalog):
    entry = catalog.entry("fixture-countries")
    with pytest.raises(ConfigError):
        select_features(catalog.load("fixture-countries"), entry, scope="galaxy")


def test_bounds(catalog):
    features = catalog.load("fixture-countries")
    assert bounds(features[:2]) == (0, 40, 20, 50)


# ---------------------------------------------------------------- projections
@pytest.mark.parametrize("projection", [equirectangular, equal_earth])
def test_origin_maps_to_origin(projection):
    assert projection(0.0, 0.0) == pytest.approx((0.0, 0.0))


@pytest.mark.parametrize("projection", [equirectangular, equal_earth])
def test_projections_are_symmetric(projection):
    x, y = projection(73.0, 41.0)
    assert projection(-73.0, 41.0) == pytest.approx((-x, y))
    assert projection(73.0, -41.0) == pytest.approx((x, -y))


def test_equal_earth_reference_extent():
    # Šavrič, Patterson & Jenny (2018): x at (180°, 0°) = π / (M · A1) ≈ 2.70663.
    x, _ = equal_earth(180.0, 0.0)
    assert x == pytest.approx(math.pi / (math.sqrt(3) / 2 * 1.340264), rel=1e-9)
    assert x == pytest.approx(2.70663, abs=1e-5)
    _, y = equal_earth(0.0, 90.0)
    assert y == pytest.approx(1.3173627, abs=1e-6)


def test_equirectangular_standard_parallel_shrinks_x():
    x_equator, _ = equirectangular(10.0, 50.0)
    x_corrected, _ = equirectangular(10.0, 50.0, standard_parallel=60.0)
    assert x_corrected == pytest.approx(x_equator * 0.5)


def test_resolve_projection_rejects_unknown():
    assert resolve_projection("equal-earth") is equal_earth
    with pytest.raises(ConfigError):
        resolve_projection("mercator")
