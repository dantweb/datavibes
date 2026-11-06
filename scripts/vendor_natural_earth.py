"""Slim a Natural Earth admin-0 GeoJSON into the vendored map geometry.

Keeps only the properties the map framework reads and quantises coordinates to
3 decimals (~100 m, far below one pixel on a 1000 px world map). Output is
written with sorted keys and fixed separators so it is byte-stable; the sha256
it prints goes into ``datavibes/maps/geometry/manifest.yaml``.

Usage (see ``make geometry``):
    python scripts/vendor_natural_earth.py <input.geojson> <output.geojson>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

KEPT_PROPERTIES = ("ADM0_A3", "NAME", "CONTINENT", "REGION_UN", "SUBREGION")
DECIMALS = 3


def _round(coordinates):
    if isinstance(coordinates[0], (int, float)):
        return [round(coordinates[0], DECIMALS), round(coordinates[1], DECIMALS)]
    return [_round(part) for part in coordinates]


def slim(collection: dict) -> dict:
    features = []
    for feature in collection["features"]:
        properties = {key: feature["properties"].get(key) for key in KEPT_PROPERTIES}
        geometry = feature["geometry"]
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": geometry["type"],
                    "coordinates": _round(geometry["coordinates"]),
                },
            }
        )
    features.sort(key=lambda item: item["properties"]["ADM0_A3"])
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str]) -> int:
    source, target = Path(argv[1]), Path(argv[2])
    collection = json.loads(source.read_text(encoding="utf-8"))
    body = json.dumps(slim(collection), sort_keys=True, separators=(",", ":")) + "\n"
    target.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    print(f"wrote {target} ({len(body)} bytes) sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
