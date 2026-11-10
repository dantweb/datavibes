"""Gridded population density as a coloured surface under the map's dots.

The vendored grid is a small pyramid derived from GHSL GHS-POP (see
``scripts/vendor_population_grid.py``): the same people/km² surface at a few
cell sizes, each stored as gzip-compressed little-endian ``uint16`` rows from
north to south. A map samples the level whose cells are about one image pixel,
so a world map averages rather than aliases and a regional map stays sharp.

Pure Python on purpose: the map runtime needs no numpy. One PNG of about
600×400 pixels takes well under a second.
"""

from __future__ import annotations

import gzip
import hashlib
import math
import struct
import sys
import zlib
from array import array
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Sequence

import yaml

from datavibes.errors import ConfigError
from datavibes.maps.color_math import hex_to_rgb

RASTER_DIR = Path(__file__).parent / "rasters"
MANIFEST = RASTER_DIR / "manifest.yaml"


@dataclass(frozen=True)
class GridLevel:
    file: str
    cell_deg: float
    width: int
    height: int
    sha256: str


@dataclass(frozen=True)
class GridEntry:
    name: str
    levels: tuple[GridLevel, ...]   # finest first
    lon_min: float
    lat_max: float
    unit: str
    attribution: str
    license: str
    source_url: str
    version: str


def load_entry(name: str, manifest: Path = MANIFEST) -> GridEntry:
    entries = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    raw = entries.get(name)
    if raw is None:
        raise ConfigError(f"unknown raster '{name}' (known: {', '.join(sorted(entries))})")
    levels = tuple(sorted((GridLevel(**level) for level in raw["levels"]), key=lambda level: level.cell_deg))
    return GridEntry(name=name, levels=levels, lon_min=float(raw["lon_min"]), lat_max=float(raw["lat_max"]),
                     unit=raw.get("unit", ""), attribution=raw.get("attribution", ""),
                     license=raw.get("license", ""), source_url=raw.get("source_url", ""),
                     version=str(raw.get("version", "")))


@lru_cache(maxsize=8)
def _cells(path: str, sha256: str, count: int) -> array:
    payload = Path(path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != sha256:
        raise ConfigError(f"raster {path} failed its sha256 check (got {digest})")
    values = array("H")
    values.frombytes(gzip.decompress(payload))
    if sys.byteorder == "big":
        values.byteswap()
    if len(values) != count:
        raise ConfigError(f"raster {path} holds {len(values)} cells, expected {count}")
    return values


class DensityGrid:
    """Nearest-cell lookups on one level of a vendored grid."""

    def __init__(self, entry: GridEntry, level: GridLevel, directory: Path = RASTER_DIR):
        self.entry, self.level = entry, level
        self.values = _cells(str(directory / level.file), level.sha256, level.width * level.height)

    def sample(self, lon: float, lat: float) -> int:
        """Nearest cell."""
        column = int((lon - self.entry.lon_min) / self.level.cell_deg)
        row = int((self.entry.lat_max - lat) / self.level.cell_deg)
        return self._cell(row, column)

    def blend(self, lon: float, lat: float) -> float:
        """Bilinear between the four nearest cell centres: a smooth surface, no squares."""
        x = (lon - self.entry.lon_min) / self.level.cell_deg - 0.5
        y = (self.entry.lat_max - lat) / self.level.cell_deg - 0.5
        column, row = math.floor(x), math.floor(y)
        fx, fy = x - column, y - row
        top = self._cell(row, column) * (1 - fx) + self._cell(row, column + 1) * fx
        bottom = self._cell(row + 1, column) * (1 - fx) + self._cell(row + 1, column + 1) * fx
        return top * (1 - fy) + bottom * fy

    def _cell(self, row: int, column: int) -> int:
        if 0 <= row < self.level.height:
            return self.values[row * self.level.width + column % self.level.width]
        return 0


def pick_level(entry: GridEntry, pixel_deg: float) -> GridLevel:
    """The coarsest level whose cells are at most 1.5 pixels wide (else the finest).

    Cells much smaller than a pixel would be skipped between samples (speckle);
    the coarser level has already averaged them."""
    fitting = [level for level in entry.levels if level.cell_deg <= 1.5 * pixel_deg]
    return fitting[-1] if fitting else entry.levels[0]


def density_color(low: float, high: float, colors: Sequence[str], opacity: float):
    """``value → (r, g, b, a)``: transparent below ``low``, log ramp to ``high``, flat above."""
    rgb = [hex_to_rgb(color) for color in colors]
    alpha = max(0, min(255, round(opacity * 255)))
    span = math.log(high) - math.log(low)

    def paint(value: float) -> tuple[int, int, int, int]:
        if value < low:
            return (0, 0, 0, 0)
        position = 1.0 if value >= high else (math.log(value) - math.log(low)) / span
        scaled = position * (len(rgb) - 1)
        index = min(int(scaled), len(rgb) - 2)
        fraction = scaled - index
        start, end = rgb[index], rgb[index + 1]
        return (*(round(a + (b - a) * fraction) for a, b in zip(start, end)), alpha)

    return paint


def render_rgba(width: int, height: int, locate: Callable[[float, float], tuple[float, float] | None],
                grid: DensityGrid, paint) -> bytes:
    """One RGBA scanline image; ``locate(px, py)`` maps a pixel centre to ``(lon, lat)`` or ``None``."""
    cache: dict[int, tuple[int, int, int, int]] = {}
    rows = bytearray()
    for py in range(height):
        rows.append(0)  # PNG filter type: none
        for px in range(width):
            where = locate(px + 0.5, py + 0.5)
            value = round(grid.blend(*where)) if where else 0
            color = cache.get(value)
            if color is None:
                color = cache[value] = paint(value)
            rows.extend(color)
    return bytes(rows)


def png(width: int, height: int, scanlines: bytes) -> bytes:
    """A minimal, deterministic RGBA PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(scanlines, 9)) + chunk(b"IEND", b""))
