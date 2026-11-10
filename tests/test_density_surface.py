"""Population-density surface between the dots: raster grid, colours, PNG, map layer."""

import gzip
import hashlib
import re
import struct
import zlib
from array import array
from pathlib import Path

import pytest

from datavibes.errors import ConfigError
from datavibes.maps import raster
from datavibes.maps.projection import (
    equal_earth, equal_earth_inverse, equirectangular, equirectangular_inverse,
)
from datavibes.registry import resolve_writer
from datavibes.schema.field import Field, Schema

GEOMETRY = Path(__file__).parent / "fixtures" / "geometry"


def _grid(tmp_path, cells, width=8, height=4, cell_deg=45.0, name="toy"):
    """A one-level vendored grid in tmp_path: rows north → south, uint16 little-endian."""
    values = array("H", cells)
    payload = gzip.compress(values.tobytes(), mtime=0)
    (tmp_path / "toy.u16.gz").write_bytes(payload)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"{name}:\n  lon_min: -180.0\n  lat_max: 90.0\n  unit: people/km²\n"
        f"  attribution: Toy grid\n  levels:\n    - file: toy.u16.gz\n      cell_deg: {cell_deg}\n"
        f"      width: {width}\n      height: {height}\n      sha256: {hashlib.sha256(payload).hexdigest()}\n",
        encoding="utf-8")
    return manifest


# ----------------------------------------------------------------- projections
@pytest.mark.parametrize("lon,lat", [(0, 0), (12.5, 48.1), (-170, -60), (179, 85)])
def test_inverse_projections_round_trip(lon, lat):
    assert equal_earth_inverse(*equal_earth(lon, lat)) == pytest.approx((lon, lat), abs=1e-6)
    assert equirectangular_inverse(*equirectangular(lon, lat, 40), 40) == pytest.approx((lon, lat), abs=1e-9)


def test_inverse_projections_return_none_off_the_globe():
    assert equal_earth_inverse(5.0, 0.0) is None
    assert equirectangular_inverse(4.0, 0.0) is None


# ---------------------------------------------------------------------- grid
def test_grid_samples_nearest_and_blends_between_cell_centres(tmp_path):
    cells = [0] * 32
    cells[1 * 8 + 4] = 100                     # row 1 (45°N…0°), column 4 (0°…45°E)
    entry = raster.load_entry("toy", _grid(tmp_path, cells))
    grid = raster.DensityGrid(entry, entry.levels[0], tmp_path)
    assert grid.sample(22.5, 22.5) == 100      # centre of the cell
    assert grid.sample(-22.5, 22.5) == 0
    assert grid.blend(22.5, 22.5) == pytest.approx(100)
    assert grid.blend(45.0, 22.5) == pytest.approx(50)    # halfway to the next centre
    assert grid.sample(0, -95) == 0                         # off the grid


def test_grid_refuses_a_file_that_fails_its_checksum(tmp_path):
    manifest = _grid(tmp_path, [0] * 32)
    (tmp_path / "toy.u16.gz").write_bytes(gzip.compress(b"\x00\x00" * 32, mtime=1))
    raster._cells.cache_clear()
    entry = raster.load_entry("toy", manifest)
    with pytest.raises(ConfigError, match="sha256"):
        raster.DensityGrid(entry, entry.levels[0], tmp_path)


def test_level_choice_averages_rather_than_aliases():
    levels = tuple(raster.GridLevel(f"{cell}", cell, 1, 1, "") for cell in (0.1, 0.25, 0.5))
    entry = raster.GridEntry("g", levels, -180, 90, "", "", "", "", "")
    assert raster.pick_level(entry, 0.05).cell_deg == 0.1    # finer than every level: the finest
    assert raster.pick_level(entry, 0.09).cell_deg == 0.1
    assert raster.pick_level(entry, 0.2).cell_deg == 0.25
    assert raster.pick_level(entry, 0.375).cell_deg == 0.5   # world map at ~1000 px


def test_density_colours_grey_below_low_then_blue_to_red():
    paint = raster.density_color(10, 2000, ["#0000ff", "#ff0000"], opacity=1.0)
    assert paint(9) == (0, 0, 0, 0)            # transparent: the grey basemap shows
    assert paint(10) == (0, 0, 255, 255)
    assert paint(2000) == paint(50000) == (255, 0, 0, 255)
    middle = paint((10 * 2000) ** 0.5)          # log-scale midpoint
    assert middle[0] == pytest.approx(128, abs=1) and middle[2] == pytest.approx(128, abs=1)


def test_png_is_a_valid_rgba_image():
    image = raster.png(2, 1, bytes([0, 255, 0, 0, 255, 0, 0, 255, 128]))
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    width, height, depth, color_type = struct.unpack(">IIBB", image[16:26])
    assert (width, height, depth, color_type) == (2, 1, 8, 6)
    idat = image[image.index(b"IDAT") + 4: image.index(b"IEND") - 8]
    assert zlib.decompress(idat) == bytes([0, 255, 0, 0, 255, 0, 0, 255, 128])


# ------------------------------------------------------------------ map layer
def test_dot_map_draws_a_clipped_surface_under_the_dots(tmp_path):
    manifest = _grid(tmp_path, [500] * 32)
    writer = resolve_writer("svg-dot-map", {
        "geometry": "fixture-countries", "geometry_manifest": str(GEOMETRY / "manifest.yaml"),
        "latitude_column": "lat", "longitude_column": "lon", "size_column": "population",
        "color_scale": {"type": "spectral-density", "value_column": "density"},
        "density_surface": {"grid": "toy", "raster_manifest": str(manifest)},
    })
    schema = Schema([Field(name="lat", dtype="float"), Field(name="lon", dtype="float"),
                     Field(name="population", dtype="int"), Field(name="density", dtype="float")])
    rows = [{"lat": 10.0, "lon": 10.0, "population": 200000, "density": 900.0}]
    svg = writer.write(rows, schema, tmp_path / "m.svg").read_text(encoding="utf-8")
    assert '<clipPath id="surface-land">' in svg
    image = svg.index("data:image/png;base64,")
    assert svg.index('clip-path="url(#surface-land)"') < image < svg.index("<circle ")   # under the dots
    assert "Between the cities: population density" in svg and "grey: below 10" in svg
    assert "Toy grid" in svg                                                         # credit line
    report = (tmp_path / "m.join.json").read_text(encoding="utf-8")
    assert '"grid": "toy"' in report and '"cell_deg": 45.0' in report


def test_surface_options_are_checked(tmp_path):
    manifest = _grid(tmp_path, [0] * 32)
    base = {"geometry": "fixture-countries", "geometry_manifest": str(GEOMETRY / "manifest.yaml"),
            "latitude_column": "lat", "longitude_column": "lon", "size_column": "population",
            "color_scale": {"type": "spectral-density", "value_column": "density"}}
    for bad in ({"low": 2000, "high": 10}, {"colors": ["#000000"]}, {"shade": True}):
        with pytest.raises(ConfigError):
            resolve_writer("svg-dot-map", {**base, "density_surface": {"grid": "toy", "raster_manifest": str(manifest), **bad}})


def test_vendored_ghsl_grid_loads_and_looks_right():
    entry = raster.load_entry("ghs-pop-2025")
    assert [level.cell_deg for level in entry.levels] == [0.1, 0.25, 0.5]
    grid = raster.DensityGrid(entry, entry.levels[0])
    assert grid.sample(2.35, 48.86) > 10000      # central Paris
    assert grid.sample(10.0, 25.0) < 10          # Sahara
    assert re.search(r"GHSL", entry.attribution)
