"""``svg-map`` — renders processed rows as a thermomap (choropleth) SVG.

SRP: this writer only *renders*. The numbers come from processing, the colours
from a registered :class:`~datavibes.interfaces.ColorScale`, the shapes from the
vendored :class:`~datavibes.maps.geometry.GeometryCatalog`. Next to the map it
writes ``<stem>.join.json`` so unmatched keys are visible, never silent.
"""

from __future__ import annotations

import json
import math
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
import base64

from datavibes.maps import raster
from datavibes.maps.painting import Legend, LegendBar, LegendSwatch, LegendTick, Painting
from datavibes.maps.projection import INVERSES, resolve_projection
from datavibes.provenance import Provenance
from datavibes.registry import register_writer, resolve_color_scale
from datavibes.schema.field import Schema

MARGIN = 20.0
TITLE_HEIGHT = 44.0
BBOX_EDGE_SAMPLES = 24
DEFAULT_DISCLAIMER = "Boundaries are de facto (Natural Earth) and imply no endorsement."
# Population density between the dots: grey basemap below `low`, blue → red up to `high`.
SURFACE_DEFAULTS = {
    "grid": "ghs-pop-2025",
    "low": 10.0,
    "high": 2000.0,
    "colors": ["#2f6db5", "#7d5bb0", "#c2457d", "#d63a2f"],
    "opacity": 0.85,
    "pixel_size": 1.0,
    "label": "Between the cities: population density (people/km², log scale)",
}


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
        item_label: str = "areas",
        density_surface: dict | None = None,
    ):
        if scope not in SCOPES:
            raise ConfigError(f"unknown map scope '{scope}' (expected one of {', '.join(SCOPES)})")
        if clip_bbox is not None and len(clip_bbox) != 4:
            raise ConfigError("clip_bbox must be [lon_min, lat_min, lon_max, lat_max]")
        self.catalog = GeometryCatalog(geometry_manifest or DEFAULT_MANIFEST)
        self.entry = self.catalog.entry(geometry)
        self.scale = resolve_color_scale(color_scale)
        self.projection_name = projection or ("equal-earth" if scope == "world" else "equirectangular")
        self.projection = resolve_projection(self.projection_name)
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
        # What one drawn thing is called in the coverage legend ("countries", "cities").
        self.item_label = item_label
        self.provenance = Provenance()
        self.surface = self._surface_options(density_surface) if density_surface is not None else None
        self._surface_report: dict | None = None

    @staticmethod
    def _surface_options(options: dict) -> dict:
        unknown = set(options) - set(SURFACE_DEFAULTS) - {"raster_manifest"}
        if unknown:
            raise ConfigError(f"density_surface: unknown option(s) {sorted(unknown)}")
        merged = {**SURFACE_DEFAULTS, **(options or {})}
        merged["low"], merged["high"] = float(merged["low"]), float(merged["high"])
        if not 0 < merged["low"] < merged["high"]:
            raise ConfigError("density_surface needs 0 < low < high")
        if len(merged["colors"]) < 2:
            raise ConfigError("density_surface needs at least two colours")
        manifest = merged.pop("raster_manifest", None)
        merged["entry"] = raster.load_entry(merged["grid"], Path(manifest) if manifest else raster.MANIFEST)
        merged["directory"] = Path(manifest).parent if manifest else raster.RASTER_DIR
        return merged

    def attach_provenance(self, provenance: Provenance) -> None:
        self.provenance = provenance

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
        layer, extra_legend, report = self._build_layers(features, rows, painting)
        if self.provenance.exclusions:
            report["excluded"] = self.provenance.as_dict()

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            self._render(
                features,
                layer,
                painting.legend,
                extra_legend,
                self._show_no_data(report),
                self._coverage_lines(report),
            ),
            encoding="utf-8",
        )
        if self._surface_report:
            report["density_surface"] = self._surface_report
        dest.with_suffix(".join.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return dest

    # ----------------------------------------------------------------- layers
    def _build_layers(self, features: list[MapFeature], rows: list[dict], painting: Painting):
        """Choropleth: each feature filled from its matched row.

        Returns ``(layer, extra_legend, report)``: ``layer(to_canvas)`` → SVG
        elements for the map area; ``extra_legend(left, top)`` → ``(elements,
        height)`` drawn under the colour legend; ``report`` → the join report.
        Subclasses override this to draw other map types on the same frame.
        """
        rows_by_key, fills_by_key, duplicates = self._index(rows, painting.fills)

        def layer(to_canvas, underlay=()) -> list[str]:
            return [
                self._feature_path(
                    feature,
                    to_canvas,
                    fills_by_key.get(feature.key) or self.no_data_color,
                    self._tooltip(feature, rows_by_key.get(feature.key)),
                )
                for feature in features
            ]

        report = self._join_report(features, rows, rows_by_key, fills_by_key, duplicates)
        return layer, _no_extra_legend, report

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
    def _coverage_lines(self, report: dict) -> list[str]:
        """Legend "Coverage" block: what is coloured, what is grey, what is missing."""
        drawn = report["drawn_features"]
        coloured = report["matched_features"] - len(report["features_with_missing_values"])
        label = self.item_label.capitalize()
        lines = [
            f"{label} coloured: {coloured:,} of {drawn:,} drawn",
            f"Without data (grey): {drawn - coloured:,}",
        ]
        if report["rows_not_drawn"]:
            lines.append(
                "In the data but not drawn (too small at this scale or outside the map): "
                f"{len(report['rows_not_drawn']):,}"
            )
        if self.provenance.exclusions:
            lines.append(f"Excluded from the data: {_exclusion_summary(self.provenance.as_dict())}")
        return lines

    def _show_no_data(self, report: dict) -> bool:
        """Whether the legend needs a "No data" swatch. Countries always might."""
        return True

    def _render(
        self,
        features: list[MapFeature],
        layer,
        legend,
        extra_legend,
        show_no_data: bool = True,
        coverage: Sequence[str] = (),
    ) -> str:
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

        underlay, legend = [], legend
        if self.surface is not None:
            inverse = INVERSES[self.projection_name]

            def to_lonlat(px: float, py: float):
                x = x_min + (px - MARGIN) / scale
                y = y_max - (py - map_top) / scale
                return inverse(x, y, standard_parallel)

            underlay = self._surface_image(to_lonlat, map_top, inner_width, map_height)
            legend = self._with_surface_legend(legend)
        paths = layer(to_canvas, underlay)

        legend_top = map_top + map_height + 16
        no_data = [LegendSwatch(label="No data", color=self.no_data_color)] if show_no_data else []
        legend_defs, legend_body, legend_height = svg.legend_markup(legend, no_data, MARGIN, legend_top)
        extra_body, extra_height = extra_legend(MARGIN, legend_top + legend_height)
        coverage_body, coverage_height = _coverage_markup(
            coverage, MARGIN, legend_top + legend_height + extra_height
        )
        legend_body = legend_body + extra_body + coverage_body
        surface_credit = self.surface["entry"].attribution if self.surface else ""
        footer_lines = [line for line in (self.footer, surface_credit, self.entry.attribution, self.disclaimer) if line]
        footer_top = legend_top + legend_height + extra_height + coverage_height + 14
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

    def _surface_image(self, to_lonlat, top: float, width: float, height: float) -> list[str]:
        """The density grid rendered as one PNG covering the map area."""
        options = self.surface
        step = options["pixel_size"]
        columns, rows = max(1, round(width / step)), max(1, round(height / step))

        def locate(px: float, py: float):
            return to_lonlat(MARGIN + px * width / columns, top + py * height / rows)

        # Degrees per image pixel at the map centre picks the grid level.
        centre = [locate(columns / 2 + offset, rows / 2) for offset in (0, 1)]
        pixel_deg = abs(centre[1][0] - centre[0][0]) if all(centre) else 1.0
        level = raster.pick_level(options["entry"], pixel_deg)
        grid = raster.DensityGrid(options["entry"], level, options["directory"])
        paint = raster.density_color(options["low"], options["high"], options["colors"], options["opacity"])
        image = raster.png(columns, rows, raster.render_rgba(columns, rows, locate, grid, paint))
        self._surface_report = {"grid": options["entry"].name, "cell_deg": level.cell_deg,
                                "image_px": [columns, rows], "low": options["low"], "high": options["high"]}
        href = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        return [f'<image x="{svg.number(MARGIN)}" y="{svg.number(top)}" width="{svg.number(width)}" '
                f'height="{svg.number(height)}" preserveAspectRatio="none" href="{href}"/>']

    def _with_surface_legend(self, legend: Legend) -> Legend:
        options = self.surface
        low, high, colors = options["low"], options["high"], options["colors"]
        stops = tuple((index / (len(colors) - 1), color) for index, color in enumerate(colors))
        span = math.log(high) - math.log(low)
        ticks = [LegendTick(0.0, f"{low:g}")]
        for value in (100.0, 1000.0):
            if low < value < high:
                ticks.append(LegendTick((math.log(value) - math.log(low)) / span, f"{value:,.0f}"))
        ticks.append(LegendTick(1.0, f"≥ {high:,.0f}"))
        bar = LegendBar(label=f"{options['label']} — grey: below {low:g}", stops=stops, ticks=tuple(ticks))
        return Legend(title=legend.title, bars=legend.bars + (bar,), swatches=legend.swatches)

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

    @staticmethod
    def _feature_path(feature: MapFeature, to_canvas, fill: str, tooltip: str) -> str:
        data = "".join(
            svg.ring_path([to_canvas(lon, lat) for lon, lat in ring])
            for polygon in feature.polygons
            for ring in polygon
        )
        if not data:
            return ""
        return (
            f'<path id="{svg.text(feature.key)}" fill="{fill}" fill-rule="evenodd" d="{data}">'
            f"<title>{svg.text(tooltip)}</title></path>"
        )

    def _tooltip(self, feature: MapFeature, row: dict | None) -> str:
        if row is None:
            return f"{feature.name} — no data"
        details = " · ".join(f"{column}: {_format_cell(row.get(column))}" for column in self.label_columns)
        return f"{feature.name} — {details}" if details else feature.name


def _no_extra_legend(left: float, top: float) -> tuple[list[str], float]:
    return [], 0.0


def _exclusion_summary(excluded: dict[str, int]) -> str:
    total = sum(excluded.values())
    reasons = " · ".join(f"{reason}: {count:,}" for reason, count in excluded.items())
    return f"{total:,} — {reasons}"


def _coverage_markup(lines: Sequence[str], left: float, top: float) -> tuple[list[str], float]:
    """A bold "Coverage" heading and one text line per entry under it."""
    if not lines:
        return [], 0.0
    body = [
        f'<text x="{svg.number(left)}" y="{svg.number(top + 18)}" font-size="12" '
        f'font-weight="bold" fill="{svg.TEXT_COLOR}">Coverage</text>'
    ]
    for index, line in enumerate(lines):
        body.append(
            f'<text x="{svg.number(left)}" y="{svg.number(top + 34 + 15 * index)}" font-size="11" '
            f'fill="{svg.TEXT_COLOR}">{svg.text(line)}</text>'
        )
    return body, 26 + 15 * len(lines)


def _format_cell(value: object) -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
