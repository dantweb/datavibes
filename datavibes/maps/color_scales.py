"""The built-in thermomap colour scales.

Each scale is pure: ``paint(rows)`` → per-row hex fills + a legend. Density
normalisation is delegated to :mod:`datavibes.processing.functions` — the same
helpers the CSV ``derive`` step uses — so the map and the CSV never disagree.
"""

from __future__ import annotations

import statistics
from typing import Sequence

from datavibes.errors import ConfigError
from datavibes.interfaces import ColorScale
from datavibes.maps.color_math import ColorStop, hsl_to_hex, interpolate_stops, lerp_hex
from datavibes.maps.painting import (
    Legend,
    LegendBar,
    LegendSwatch,
    LegendTick,
    Painting,
    format_quantity,
)
from datavibes.processing import functions
from datavibes.registry import register_color_scale

LEGEND_TICK_UNITS = (0.0, 0.5, 1.0)
WHITE = "#ffffff"

# Lowest → highest: dark blue, sky blue, green (= average), yellow, orange, red.
SPECTRAL_DEFAULT_COLORS = (
    "#08306b",
    "#4fc3f7",
    "#2e9e44",
    "#ffd400",
    "#ff8c00",
    "#d7191c",
)


def _check_method(method: str) -> str:
    if method not in functions.NORMALIZATION_METHODS:
        raise ConfigError(
            f"normalize must be one of {', '.join(functions.NORMALIZATION_METHODS)}, got '{method}'"
        )
    return method


def _ticks(
    values: Sequence, method: str, units: Sequence[float], upper: float | None = None
) -> tuple[LegendTick, ...]:
    """Ticks labelled in real units; with ``upper`` the top tick reads ``≥ upper``."""
    domain = functions.normalization_domain(values, method, upper=upper)
    if domain is None:
        return ()
    ticks = []
    for unit in units:
        label = format_quantity(functions.value_at_unit(unit, domain, method))
        if upper is not None and unit >= 1.0:
            label = f"≥ {format_quantity(upper)}"
        ticks.append(LegendTick(position=unit, label=label))
    return tuple(ticks)


@register_color_scale("sex-ratio-bivariate")
class SexRatioBivariateScale(ColorScale):
    """Hue = sex majority (blue: more men, red: more women); intensity = density.

    Each fill is white blended toward the full hue by the normalised density:
    ``intensity_range[0]`` (sparsest, almost white) … ``intensity_range[1]``
    (densest, fully saturated blue/red).
    """

    def __init__(
        self,
        ratio_column: str,
        value_column: str,
        normalize: str = "log",
        saturation_range: Sequence[float] = (0.1, 1.0),
        tie_tolerance_pct: float = 0.05,
        lightness: float = 0.5,
        male_hue: float = 212.0,
        female_hue: float = 0.0,
        equal_color: str = "#9e9e9e",
        value_label: str = "",
    ):
        floor, ceil = (float(bound) for bound in saturation_range)
        if not 0.0 <= floor < ceil <= 1.0:
            raise ConfigError(
                f"saturation_range must satisfy 0 <= low < high <= 1, got {list(saturation_range)}"
            )
        self.ratio_column = ratio_column
        self.value_column = value_column
        self.method = _check_method(normalize)
        self.floor = floor
        self.ceil = ceil
        self.tolerance = float(tie_tolerance_pct)
        self.lightness = float(lightness)
        self.male_hue = float(male_hue)
        self.female_hue = float(female_hue)
        self.equal_color = equal_color
        self.value_label = value_label or value_column

    def paint(self, rows: list[dict]) -> Painting:
        densities = [row.get(self.value_column) for row in rows]
        saturations = functions.scale_to_range(
            densities, method=self.method, floor=self.floor, ceil=self.ceil
        )
        majorities = functions.sex_majority(
            [row.get(self.ratio_column) for row in rows], tolerance=self.tolerance
        )
        fills = tuple(
            self._fill(majority, saturation)
            for majority, saturation in zip(majorities, saturations)
        )
        return Painting(fills=fills, legend=self._legend(densities))

    def _fill(self, majority: str | None, saturation: float | None) -> str | None:
        if majority is None or saturation is None:
            return None
        if majority == "equal":
            return self.equal_color
        hue = self.male_hue if majority == "male" else self.female_hue
        return lerp_hex(WHITE, hsl_to_hex(hue, 1.0, self.lightness), saturation)

    def _legend(self, densities: Sequence) -> Legend:
        ticks = _ticks(densities, self.method, LEGEND_TICK_UNITS)
        bars = tuple(
            LegendBar(
                label=label,
                stops=(
                    (0.0, lerp_hex(WHITE, hsl_to_hex(hue, 1.0, self.lightness), self.floor)),
                    (1.0, lerp_hex(WHITE, hsl_to_hex(hue, 1.0, self.lightness), self.ceil)),
                ),
                ticks=ticks,
            )
            for label, hue in (
                ("More men than women", self.male_hue),
                ("More women than men", self.female_hue),
            )
        )
        return Legend(
            title=f"Colour: sex majority · intensity (white → full): {self.value_label}",
            bars=bars,
            swatches=(LegendSwatch(label="≈ equal", color=self.equal_color),),
        )


@register_color_scale("spectral-density")
class SpectralDensityScale(ColorScale):
    """Dark blue (lowest) → sky blue → green (set average) → yellow → orange → red (highest)."""

    CENTERS = ("mean", "median")

    def __init__(
        self,
        value_column: str,
        normalize: str = "log",
        center: str = "mean",
        colors: Sequence[str] | None = None,
        value_label: str = "",
        saturate_above: float | str | None = None,
    ):
        if center not in self.CENTERS:
            raise ConfigError(f"center must be one of {', '.join(self.CENTERS)}, got '{center}'")
        palette = tuple(colors) if colors is not None else SPECTRAL_DEFAULT_COLORS
        if len(palette) != len(SPECTRAL_DEFAULT_COLORS):
            raise ConfigError(
                f"spectral-density needs exactly {len(SPECTRAL_DEFAULT_COLORS)} colors "
                "(dark blue, sky blue, green, yellow, orange, red)"
            )
        self.value_column = value_column
        self.method = _check_method(normalize)
        self.center = center
        self.colors = palette
        self.saturate_above = None if saturate_above in (None, "") else float(saturate_above)
        if self.saturate_above is not None and self.method == "log" and self.saturate_above <= 0:
            raise ConfigError("saturate_above must be > 0 on a log scale")
        self.value_label = value_label or value_column

    def stops_for_center(self, center: float) -> list[ColorStop]:
        """Two segments below the average, three above it."""
        above = 1.0 - center
        positions = (
            0.0,
            center / 2.0,
            center,
            center + above / 3.0,
            center + above * 2.0 / 3.0,
            1.0,
        )
        return list(zip(positions, self.colors))

    def paint(self, rows: list[dict]) -> Painting:
        values = [row.get(self.value_column) for row in rows]
        units = functions.unit_normalize(values, method=self.method, upper=self.saturate_above)
        center = self._center([unit for unit in units if unit is not None])
        stops = self.stops_for_center(center)
        fills = tuple(
            None if unit is None else interpolate_stops(stops, unit) for unit in units
        )
        top = "highest" if self.saturate_above is None else f"red = overpopulated (≥ {format_quantity(self.saturate_above)})"
        legend = Legend(
            title=f"{self.value_label} (green = average)",
            bars=(
                LegendBar(
                    label=f"Lowest → {top}",
                    stops=tuple(stops),
                    ticks=_ticks(values, self.method, (0.0, center, 1.0), upper=self.saturate_above),
                ),
            ),
        )
        return Painting(fills=fills, legend=legend)

    def _center(self, units: list[float]) -> float:
        if not units:
            return 0.5
        if self.center == "median":
            return statistics.median(units)
        return statistics.fmean(units)
