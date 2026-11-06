"""Vendored map geometry — a checksummed catalog plus scope selection.

Geometry is a shared asset, not per-run data: the files ship inside the package
(``datavibes/maps/geometry/``) with a manifest recording source, version and
sha256. Loading never touches the network, so rendering is deterministic and
works offline in CI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from datavibes.errors import ConfigError, DatavibesError

DEFAULT_MANIFEST = Path(__file__).parent / "geometry" / "manifest.yaml"
SCOPES = ("world", "region", "country")

Ring = tuple[tuple[float, float], ...]
Polygon = tuple[Ring, ...]  # outer ring first, then holes


@dataclass(frozen=True)
class GeometryEntry:
    """One manifest entry: where a geometry file lives and how to read it."""

    name: str
    file: Path
    level: str
    key_property: str
    name_property: str
    sha256: str
    continent_property: str | None = None
    country_property: str | None = None
    source_url: str = ""
    version: str = ""
    license: str = ""
    attribution: str = ""


@dataclass(frozen=True)
class MapFeature:
    """One drawable area (a country or a subdivision)."""

    key: str
    name: str
    polygons: tuple[Polygon, ...]
    properties: dict = field(default_factory=dict, hash=False, compare=False)


class GeometryCatalog:
    """Reads the manifest and loads (and verifies) the geometry files it lists."""

    def __init__(self, manifest_path: str | Path = DEFAULT_MANIFEST):
        self.manifest_path = Path(manifest_path)
        self._entries = self._read_manifest()
        self._cache: dict[str, list[MapFeature]] = {}

    def entry(self, name: str) -> GeometryEntry:
        entry = self._entries.get(name)
        if entry is None:
            raise ConfigError(
                f"unknown geometry '{name}' (known: {', '.join(sorted(self._entries)) or 'none'})"
            )
        return entry

    def load(self, name: str) -> list[MapFeature]:
        if name not in self._cache:
            self._cache[name] = self._load_entry(self.entry(name))
        return self._cache[name]

    def _read_manifest(self) -> dict[str, GeometryEntry]:
        if not self.manifest_path.is_file():
            raise ConfigError(f"geometry manifest not found: {self.manifest_path}")
        raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        entries: dict[str, GeometryEntry] = {}
        for name, block in raw.items():
            options = dict(block)
            options["file"] = self.manifest_path.parent / options["file"]
            try:
                entries[name] = GeometryEntry(name=name, **options)
            except TypeError as exc:
                raise ConfigError(f"geometry '{name}': invalid manifest entry ({exc})") from exc
        return entries

    @staticmethod
    def _load_entry(entry: GeometryEntry) -> list[MapFeature]:
        body = entry.file.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != entry.sha256:
            raise DatavibesError(
                f"geometry file {entry.file.name} failed its checksum "
                f"(expected {entry.sha256}, got {digest}); re-vendor it or update the manifest"
            )
        collection = json.loads(body.decode("utf-8"))
        features = [
            MapFeature(
                key=str(item["properties"][entry.key_property]),
                name=str(item["properties"].get(entry.name_property, "")),
                polygons=_polygons(item["geometry"]),
                properties=dict(item["properties"]),
            )
            for item in collection["features"]
        ]
        return sorted(features, key=lambda feature: feature.key)


def select_features(
    features: Sequence[MapFeature],
    entry: GeometryEntry,
    scope: str,
    region: dict | None = None,
    country: str | None = None,
    exclude: Iterable[str] = (),
) -> list[MapFeature]:
    """Filter ``features`` to what a ``world`` / ``region`` / ``country`` map draws."""
    excluded = set(exclude)
    if scope == "world":
        selected = list(features)
    elif scope == "region":
        selected = _select_region(features, entry, region or {})
    elif scope == "country":
        selected = _select_country(features, entry, country)
    else:
        raise ConfigError(f"unknown map scope '{scope}' (expected one of {', '.join(SCOPES)})")
    return [feature for feature in selected if feature.key not in excluded]


def bounds(features: Iterable[MapFeature]) -> tuple[float, float, float, float]:
    """``(lon_min, lat_min, lon_max, lat_max)`` over every ring point."""
    lons: list[float] = []
    lats: list[float] = []
    for feature in features:
        for polygon in feature.polygons:
            for ring in polygon:
                for lon, lat in ring:
                    lons.append(lon)
                    lats.append(lat)
    if not lons:
        raise ConfigError("cannot compute bounds of an empty feature set")
    return min(lons), min(lats), max(lons), max(lats)


def _select_region(
    features: Sequence[MapFeature], entry: GeometryEntry, region: dict
) -> list[MapFeature]:
    codes = region.get("iso3")
    continent = region.get("continent")
    if codes:
        wanted = set(codes)
        return [feature for feature in features if feature.key in wanted]
    if continent:
        if not entry.continent_property:
            raise ConfigError(f"geometry '{entry.name}' has no continent property")
        return [
            feature
            for feature in features
            if feature.properties.get(entry.continent_property) == continent
        ]
    raise ConfigError("region scope needs 'region: {iso3: [...]}' or 'region: {continent: ...}'")


def _select_country(
    features: Sequence[MapFeature], entry: GeometryEntry, country: str | None
) -> list[MapFeature]:
    if entry.level != "admin1" or not entry.country_property:
        raise ConfigError(
            f"country scope needs admin1 geometry with a country property; "
            f"'{entry.name}' is {entry.level}"
        )
    if not country:
        raise ConfigError("country scope needs 'country: <ISO3>'")
    return [
        feature
        for feature in features
        if feature.properties.get(entry.country_property) == country
    ]


def _polygons(geometry: dict) -> tuple[Polygon, ...]:
    kind = geometry["type"]
    if kind == "Polygon":
        parts = [geometry["coordinates"]]
    elif kind == "MultiPolygon":
        parts = geometry["coordinates"]
    else:
        raise ConfigError(f"unsupported geometry type '{kind}'")
    return tuple(
        tuple(tuple((float(lon), float(lat)) for lon, lat in ring) for ring in polygon)
        for polygon in parts
    )
