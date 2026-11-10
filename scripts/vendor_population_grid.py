"""Condense the GHSL population grid into the vendored density pyramid.

Input: GHS-POP R2023A, epoch 2025, 30 arc-second WGS84 GeoTIFF (~1 km cells,
people per cell), from the European Commission's Joint Research Centre,
CC BY 4.0:
  https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/
  GHS_POP_E2025_GLOBE_R2023A_4326_30ss/V1-0/GHS_POP_E2025_GLOBE_R2023A_4326_30ss_V1_0.zip

Output: people/km² at 0.1°, 0.25° and 0.5° on a global grid anchored at
(180°W, 90°N), north to south, as gzip-compressed little-endian uint16 (capped
at 65,535), plus the manifest entry with each file's sha256. Population is
summed per output cell and divided by the cell's true spherical area, so
coastal cells include water area. The gzip header carries no timestamp, so the
bytes are reproducible.

Needs numpy and tifffile (+ imagecodecs); the map runtime needs neither.
Usage:
    python scripts/vendor_population_grid.py <GHS_POP_...30ss_V1_0.tif>
"""

from __future__ import annotations

import gzip
import hashlib
import sys
from pathlib import Path

import numpy as np
import tifffile
import yaml

OUT = Path(__file__).resolve().parents[1] / "datavibes" / "maps" / "rasters"
SOURCE_ARCSEC = 30
LEVELS = {"0p1": 0.1, "0p25": 0.25, "0p5": 0.5}
EARTH_RADIUS_KM = 6371.0088
NAME = "ghs-pop-2025"


def read_global(path: Path) -> np.ndarray:
    """The GeoTIFF as a float64 array padded to the full globe at 30″."""
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        scale = page.tags["ModelPixelScaleTag"].value
        tie = page.tags["ModelTiepointTag"].value
        data = page.asarray().astype(np.float64)
    cell = SOURCE_ARCSEC / 3600.0
    if abs(scale[0] - cell) > 1e-9 or abs(scale[1] - cell) > 1e-9:
        raise SystemExit(f"expected {SOURCE_ARCSEC}\" cells, got {scale[:2]}")
    lon0, lat0 = tie[3], tie[4]
    data[~np.isfinite(data) | (data < 0)] = 0.0
    full = np.zeros((int(round(180 / cell)), int(round(360 / cell))))
    # GHSL's origin sits about one cell west of 180°W; round it to the global grid
    # (a ~1 km shift) and crop whatever falls outside.
    row0, col0 = int(round((90 - lat0) / cell)), int(round((lon0 + 180) / cell))
    src_r, src_c = max(0, -row0), max(0, -col0)
    dst_r, dst_c = max(0, row0), max(0, col0)
    rows = min(data.shape[0] - src_r, full.shape[0] - dst_r)
    cols = min(data.shape[1] - src_c, full.shape[1] - dst_c)
    full[dst_r:dst_r + rows, dst_c:dst_c + cols] = data[src_r:src_r + rows, src_c:src_c + cols]
    print(f"read {data.shape} from lon {lon0:.4f}, lat {lat0:.4f}; placed at row {dst_r}, col {dst_c}; "
          f"population {data.sum() / 1e9:.3f} bn, kept {full.sum() / 1e9:.3f} bn")
    return full


def cell_areas_km2(rows: int, cell_deg: float) -> np.ndarray:
    tops = np.radians(90 - cell_deg * np.arange(rows))
    bottoms = np.radians(90 - cell_deg * (np.arange(rows) + 1))
    return EARTH_RADIUS_KM ** 2 * np.radians(cell_deg) * (np.sin(tops) - np.sin(bottoms))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    population = read_global(Path(argv[0]))
    OUT.mkdir(parents=True, exist_ok=True)
    levels = []
    for suffix, cell_deg in LEVELS.items():
        factor = int(round(cell_deg * 3600 / SOURCE_ARCSEC))
        rows, cols = population.shape[0] // factor, population.shape[1] // factor
        sums = population.reshape(rows, factor, cols, factor).sum(axis=(1, 3))
        density = sums / cell_areas_km2(rows, cell_deg)[:, None]
        values = np.clip(np.rint(density), 0, 65535).astype("<u2")
        payload = gzip.compress(values.tobytes(), compresslevel=9, mtime=0)
        name = f"ghs_pop_2025_density_{suffix}.u16.gz"
        (OUT / name).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        levels.append({"file": name, "cell_deg": cell_deg, "width": cols, "height": rows, "sha256": digest})
        print(f"{name}: {cols}x{rows}, {len(payload) / 1e6:.2f} MB, sha256 {digest}")
    manifest = {
        NAME: {
            "lon_min": -180.0,
            "lat_max": 90.0,
            "unit": "people/km²",
            "levels": levels,
            "source_url": "https://ghsl.jrc.ec.europa.eu/download.php?ds=pop",
            "version": "GHS-POP R2023A, epoch 2025, 30 arc-seconds",
            "license": "CC BY 4.0 (European Commission, Joint Research Centre)",
            "attribution": "Density between cities: GHSL GHS-POP R2023A, 2025 (European Commission, JRC), CC BY 4.0",
        }
    }
    header = "# Vendored population-density grids. Each file is verified against its sha256 on load.\n" \
             "# Refresh with `make population-grid` (scripts/vendor_population_grid.py).\n"
    (OUT / "manifest.yaml").write_text(header + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
