"""``svg-dot-map`` — one dot per row (e.g. per city) on a neutral country basemap.

Dot **area** is proportional to ``size_column`` (radius ∝ √size, the
perceptually honest choice). Dot **colour** comes from the same registered
colour scales as the choropleth, so a dataset swaps between a country map and a
city map by changing its output, not its colour logic. Largest dots are drawn
first so small ones stay visible on top.
"""

from __future__ import annotations

import math
from typing import Sequence

from datavibes.errors import ConfigError
from datavibes.maps import svg
from datavibes.maps.geometry import MapFeature
from datavibes.maps.painting import Painting, format_quantity
from datavibes.maps.svg_writer import SvgMapWriter, _exclusion_summary, _format_cell
from datavibes.registry import register_writer

SIZE_LEGEND_GAP = 18.0


@register_writer("svg-dot-map")
class SvgDotMapWriter(SvgMapWriter):
    """Proportional-symbol map: position from lat/lon, area from size, fill from a colour scale."""

    def __init__(
        self,
        latitude_column: str,
        longitude_column: str,
        size_column: str,
        name_column: str | None = None,
        size_label: str = "",
        min_radius: float = 1.0,
        max_radius: float = 12.0,
        size_legend: Sequence[float] = (100_000, 1_000_000, 10_000_000),
        basemap_color: str = "#e3e6ea",
        dot_opacity: float = 0.85,
        dot_stroke: str = "#ffffff",
        **options,
    ):
        options.setdefault("key_column", "")
        options.setdefault("item_label", "points")
        super().__init__(**options)
        if not 0 < float(min_radius) <= float(max_radius):
            raise ConfigError("svg-dot-map needs 0 < min_radius <= max_radius")
        self.latitude_column = latitude_column
        self.longitude_column = longitude_column
        self.size_column = size_column
        self.name_column = name_column
        self.size_label = size_label or size_column
        self.min_radius = float(min_radius)
        self.max_radius = float(max_radius)
        self.size_legend = tuple(float(value) for value in size_legend)
        self.basemap_color = basemap_color
        self.dot_opacity = float(dot_opacity)
        self.dot_stroke = dot_stroke

    def _build_layers(self, features: list[MapFeature], rows: list[dict], painting: Painting):
        points = []  # (row index, row, fill, lon, lat, size)
        missing_coordinates = 0
        for index, (row, fill) in enumerate(zip(rows, painting.fills)):
            lon, lat = _number(row.get(self.longitude_column)), _number(row.get(self.latitude_column))
            if lon is None or lat is None:
                missing_coordinates += 1
                continue
            points.append((index, row, fill, lon, lat, max(_number(row.get(self.size_column)) or 0.0, 0.0)))
        largest = max((point[5] for point in points), default=0.0)

        def radius(size: float) -> float:
            if largest <= 0:
                return self.min_radius
            return max(self.min_radius, self.max_radius * math.sqrt(size / largest))

        # Largest first so small dots stay on top; row index breaks ties (determinism).
        ordered = sorted(points, key=lambda point: (-point[5], point[0]))

        def layer(to_canvas, underlay=()) -> list[str]:
            basemap = [
                self._feature_path(feature, to_canvas, self.basemap_color, feature.name)
                for feature in features
            ]
            dots = []
            for _, row, fill, lon, lat, size in ordered:
                x, y = to_canvas(lon, lat)
                dots.append(
                    f'<circle cx="{svg.number(x)}" cy="{svg.number(y)}" r="{svg.number(radius(size))}" '
                    f'fill="{fill or self.no_data_color}" fill-opacity="{self.dot_opacity}" '
                    f'stroke="{self.dot_stroke}" stroke-width="0.3"><title>{svg.text(self._dot_tooltip(row))}</title></circle>'
                )
            if underlay:
                # The density surface shows only on land the map draws (the region's countries).
                mask = ["<defs><clipPath id=\"surface-land\">", *basemap, "</clipPath></defs>"]
                underlay = mask + ['<g clip-path="url(#surface-land)">', *underlay, "</g>"]
            return basemap + list(underlay) + dots

        def extra_legend(left: float, top: float) -> tuple[list[str], float]:
            values = [value for value in self.size_legend if value > 0]
            if not values or largest <= 0:
                return [], 0.0
            radii = [radius(value) for value in values]
            tallest = max(radii)
            body = [
                f'<text x="{svg.number(left)}" y="{svg.number(top + 12)}" font-size="11" '
                f'fill="{svg.TEXT_COLOR}">Dot area: {svg.text(self.size_label)}</text>'
            ]
            baseline = top + 20 + 2 * tallest
            cursor = left
            for value, size_radius in zip(values, radii):
                label = format_quantity(value)
                width = max(2 * size_radius, 6.5 * len(label))
                center = cursor + width / 2
                body.append(
                    f'<circle cx="{svg.number(center)}" cy="{svg.number(baseline - size_radius)}" '
                    f'r="{svg.number(size_radius)}" fill="none" stroke="{svg.TEXT_COLOR}" stroke-width="0.8"/>'
                )
                body.append(
                    f'<text x="{svg.number(center)}" y="{svg.number(baseline + 13)}" font-size="10" '
                    f'text-anchor="middle" fill="{svg.TEXT_COLOR}">{svg.text(label)}</text>'
                )
                cursor += width + SIZE_LEGEND_GAP
            return body, baseline + 13 - top

        report = {
            "geometry": self.entry.name,
            "scope": self.scope,
            "drawn_points": len(points),
            "points_without_color": sum(1 for point in points if point[2] is None),
            "rows_without_coordinates": missing_coordinates,
        }
        return layer, extra_legend, report

    def _coverage_lines(self, report: dict) -> list[str]:
        """"Cities shown: 3,236 of 4,017" + why the rest are not on the map."""
        excluded = dict(self.provenance.as_dict())
        if report["rows_without_coordinates"]:
            excluded["no coordinates"] = report["rows_without_coordinates"]
        shown = report["drawn_points"]
        total = shown + sum(excluded.values())
        lines = [f"{self.item_label.capitalize()} shown: {shown:,} of {total:,}"]
        lines.append(f"Not included: {_exclusion_summary(excluded)}" if excluded else "Not included: none")
        if report["points_without_color"]:
            lines.append(f"Shown without colour (grey): {report['points_without_color']:,}")
        return lines

    def _show_no_data(self, report: dict) -> bool:
        # The basemap is neutral, not "no data"; only uncoloured dots need the swatch.
        return report["points_without_color"] > 0

    def _dot_tooltip(self, row: dict) -> str:
        details = " · ".join(
            f"{column}: {_format_cell(row.get(column))}" for column in self.label_columns
        )
        if self.name_column:
            name = _format_cell(row.get(self.name_column))
            return f"{name} — {details}" if details else name
        return details


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number
