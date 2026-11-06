"""``svg-map`` — renders processed rows as a thermomap (choropleth) SVG.

SRP: this writer only *renders*. The numbers come from processing, the colours
from a registered :class:`~datavibes.interfaces.ColorScale`, the shapes from the
vendored :class:`~datavibes.maps.geometry.GeometryCatalog`. Next to the map it
writes ``<stem>.join.json`` so unmatched keys are visible, never silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from datavibes.errors import ConfigError
from datavibes.interfaces import Writer
from datavibes.maps import svg
from datavibes.maps.geometry import (
    DEFAULT_MANIFEST,
    SCOPES,
    GeometryCatalog,
    MapFeature,
    bounds,
    select_features,
)
from datavibes.maps.painting import LegendSwatch
from datavibes.maps.projection import resolve_projection
from datavibes.registry import register_writer, resolve_color_scale
from datavibes.schema.field import Schema

MARGIN = 20.0
TITLE_HEIGHT = 44.0
BBOX_EDGE_SAMPLES = 24
DEFAULT_DISCLAIMER = "Boundaries are de facto (Natural Earth) and imply no endorsement."


@register_writer("svg-map")
class SvgMapWriter(Writer):
    """Thermomap renderer for ``world`` / ``region`` / ``country`` scopes."""

    extension = "svg"

    def __init__(
        self,
        geometry: str,
        color_scale: dict,
        key_column: str,
        scope: str = "world",
        region: dict | None = None,
        country: str | None = None,
        clip_bbox: Sequence[float] | None = None,
        exclude: Sequence[str] = (),
        projection: str | None = None,
        key_aliases: dict | None = None,
        label_columns: Sequence[str] = (),
        title: str = "",
        footer: str = "",
        disclaimer: str = DEFAULT_DISCLAIMER,
        width: float = 1000.0,
        background: str = "#ffffff",
        no_data_color: str = "#d9d9d9",
        border_color: str = "#ffffff",
        border_width: float = 0.3,
        geometry_manifest: str | None = None,
    ):
        if scope not in SCOPES:
            raise ConfigError(f"unknown map scope '{scope}' (expected one of {', '.join(SCOPES)})")
        if clip_bbox is not None and len(clip_bbox) != 4:
            raise ConfigError("clip_bbox must be [lon_min, lat_min, lon_max, lat_max]")
        self.catalog = GeometryCatalog(geometry_manifest or DEFAULT_MANIFEST)
        self.entry = self.catalog.entry(geometry)
        self.scale = resolve_color_scale(color_scale)
        self.projection = resolve_projection(
            projection or ("equal-earth" if scope == "world" else "equirectangular")
        )
        self.scope = scope
        self.region = region
        self.country = country
        self.clip_bbox = tuple(float(value) for value in clip_bbox) if clip_bbox else None
        self.exclude = tuple(exclude)
        self.key_column = key_column
        self.key_aliases = {str(key): str(value) for key, value in (key_aliases or {}).items()}
        self.label_columns = tuple(label_columns)
        self.title = title
        self.footer = footer
        self.disclaimer = disclaimer
        self.width = float(width)
        self.background = background
        self.no_data_color = no_data_color
        self.border_color = border_color
        self.border_width = float(border_width)

    # ------------------------------------------------------------------ write
    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path:
        features = select_features(
            self.catalog.load(self.entry.name),
            self.entry,
            scope=self.scope,
            region=self.region,
            country=self.country,
            exclude=self.exclude,
        )
        if not features:
            raise ConfigError(f"map scope '{self.scope}' selected no features from '{self.entry.name}'")

        # The colour domain is the whole dataset (all rows), so map and CSV agree.
        painting = self.scale.paint(rows)
        rows_by_key, fills_by_key, duplicates = self._index(rows, painting.fills)

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self._render(features, rows_by_key, fills_by_key, painting.legend), encoding="utf-8")
        report = self._join_report(features, rows, rows_by_key, fills_by_key, duplicates)
        dest.with_suffix(".join.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return dest

    # ------------------------------------------------------------------- join
    def _key_for(self, row: dict) -> str | None:
        raw = row.get(self.key_column)
        if raw is None or raw == "":
            return None
        return self.key_aliases.get(str(raw), str(raw))

    def _index(self, rows, fills):
        rows_by_key: dict[str, dict] = {}
        fills_by_key: dict[str, str | None] = {}
        duplicates: set[str] = set()
        for row, fill in zip(rows, fills):
            key = self._key_for(row)
            if key is None:
                continue
            if key in rows_by_key:
                duplicates.add(key)
                continue
            rows_by_key[key] = row
            fills_by_key[key] = fill
        return rows_by_key, fills_by_key, duplicates

    def _join_report(self, features, rows, rows_by_key, fills_by_key, duplicates) -> dict:
        drawn = {feature.key for feature in features}
        return {
            "geometry": self.entry.name,
            "scope": self.scope,
            "drawn_features": len(features),
            "matched_features": sum(1 for key in drawn if key in rows_by_key),
            "features_without_rows": sorted(key for key in drawn if key not in rows_by_key),
            "features_with_missing_values": sorted(
                key for key in drawn if key in rows_by_key and fills_by_key.get(key) is None
            ),
            "rows_not_drawn": sorted(
                {
                    str(row.get(self.key_column))
                    for row in rows
                    if self._key_for(row) is not None and self._key_for(row) not in drawn
                }
            ),
            "duplicate_row_keys": sorted(duplicates),
        }

    # ----------------------------------------------------------------- render
    def _render(self, features: list[MapFeature], rows_by_key, fills_by_key, legend) -> str:
        standard_parallel = 0.0
        if self.scope != "world":
            lon_min, lat_min, lon_max, lat_max = self.clip_bbox or bounds(features)
            standard_parallel = (lat_min + lat_max) / 2.0

        def project(lon: float, lat: float) -> tuple[float, float]:
            return self.projection(lon, lat, standard_parallel=standard_parallel)

        x_min, y_min, x_max, y_max = self._extent(features, project)
        inner_width = self.width - 2 * MARGIN
        span_x = max(x_max - x_min, 1e-9)
        scale = inner_width / span_x
        map_top = TITLE_HEIGHT if self.title else MARGIN
        map_height = (y_max - y_min) * scale

        def to_canvas(lon: float, lat: float) -> tuple[float, float]:
            x, y = project(lon, lat)
            return MARGIN + (x - x_min) * scale, map_top + (y_max - y) * scale

        paths = [self._feature_path(feature, to_canvas, rows_by_key, fills_by_key) for feature in features]

        legend_top = map_top + map_height + 16
        legend_defs, legend_body, legend_height = svg.legend_markup(
            legend, [LegendSwatch(label="No data", color=self.no_data_color)], MARGIN, legend_top
        )
        footer_lines = [line for line in (self.footer, self.entry.attribution, self.disclaimer) if line]
        footer_top = legend_top + legend_height + 14
        height = footer_top + 14 * len(footer_lines) + MARGIN / 2

        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg.number(self.width)} {svg.number(height)}" '
            f'width="{svg.number(self.width)}" height="{svg.number(height)}" {svg.FONT}>',
            "<defs>",
            f'<clipPath id="map-area"><rect x="{svg.number(MARGIN)}" y="{svg.number(map_top)}" '
            f'width="{svg.number(inner_width)}" height="{svg.number(map_height)}"/></clipPath>',
            *legend_defs,
            "</defs>",
            f'<rect x="0" y="0" width="{svg.number(self.width)}" height="{svg.number(height)}" fill="{self.background}"/>',
        ]
        if self.title:
            parts.append(
                f'<text x="{svg.number(MARGIN)}" y="30.0" font-size="20" font-weight="bold" '
                f'fill="{svg.TEXT_COLOR}">{svg.text(self.title)}</text>'
            )
        parts.append(
            f'<g clip-path="url(#map-area)" stroke="{self.border_color}" '
            f'stroke-width="{self.border_width}" stroke-linejoin="round">'
        )
        parts.extend(path for path in paths if path)
        parts.append("</g>")
        parts.extend(legend_body)
        for index, line in enumerate(footer_lines):
            parts.append(
                f'<text x="{svg.number(MARGIN)}" y="{svg.number(footer_top + 14 * index)}" '
                f'font-size="10" fill="#666666">{svg.text(line)}</text>'
            )
        parts.append("</svg>")
        return "\n".join(parts) + "\n"

    def _extent(self, features, project) -> tuple[float, float, float, float]:
        if self.clip_bbox:
            lon_min, lat_min, lon_max, lat_max = self.clip_bbox
            steps = [index / BBOX_EDGE_SAMPLES for index in range(BBOX_EDGE_SAMPLES + 1)]
            points = []
            for step in steps:
                lon = lon_min + (lon_max - lon_min) * step
                lat = lat_min + (lat_max - lat_min) * step
                points += [(lon, lat_min), (lon, lat_max), (lon_min, lat), (lon_max, lat)]
            projected = [project(lon, lat) for lon, lat in points]
        else:
            projected = [
                project(lon, lat)
                for feature in features
                for polygon in feature.polygons
                for ring in polygon
                for lon, lat in ring
            ]
        xs = [x for x, _ in projected]
        ys = [y for _, y in projected]
        return min(xs), min(ys), max(xs), max(ys)

    def _feature_path(self, feature: MapFeature, to_canvas, rows_by_key, fills_by_key) -> str:
        data = "".join(
            svg.ring_path([to_canvas(lon, lat) for lon, lat in ring])
            for polygon in feature.polygons
            for ring in polygon
        )
        if not data:
            return ""
        fill = fills_by_key.get(feature.key) or self.no_data_color
        return (
            f'<path id="{svg.text(feature.key)}" fill="{fill}" fill-rule="evenodd" d="{data}">'
            f"<title>{svg.text(self._tooltip(feature, rows_by_key.get(feature.key)))}</title></path>"
        )

    def _tooltip(self, feature: MapFeature, row: dict | None) -> str:
        if row is None:
            return f"{feature.name} — no data"
        details = " · ".join(f"{column}: {_format_cell(row.get(column))}" for column in self.label_columns)
        return f"{feature.name} — {details}" if details else feature.name


def _format_cell(value: object) -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
