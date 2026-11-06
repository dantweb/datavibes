"""S13 — colour math + the two thermomap colour scales (pure)."""

import colorsys

import pytest

from datavibes.errors import ConfigError, UnknownStrategyError
from datavibes.maps import color_math
from datavibes.maps.color_scales import (
    SPECTRAL_DEFAULT_COLORS,
    SexRatioBivariateScale,
    SpectralDensityScale,
)
from datavibes.registry import COLOR_SCALE_REGISTRY, resolve_color_scale


# ------------------------------------------------------------------ colour math
def test_hsl_to_hex_pure_hues():
    assert color_math.hsl_to_hex(0, 1.0, 0.5) == "#ff0000"
    assert color_math.hsl_to_hex(120, 1.0, 0.5) == "#00ff00"
    assert color_math.hsl_to_hex(240, 1.0, 0.5) == "#0000ff"


def test_hsl_to_hex_low_saturation_is_near_grey_with_same_hue():
    red, green, blue = color_math.hex_to_rgb(color_math.hsl_to_hex(212, 0.1, 0.5))
    assert max(red, green, blue) - min(red, green, blue) < 30
    hue, _, _ = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    assert hue * 360 == pytest.approx(212, abs=4)


def test_lerp_hex_endpoints_and_midpoint():
    assert color_math.lerp_hex("#000000", "#ffffff", 0.0) == "#000000"
    assert color_math.lerp_hex("#000000", "#ffffff", 1.0) == "#ffffff"
    assert color_math.lerp_hex("#000000", "#ffffff", 0.5) == "#808080"


def test_interpolate_stops_hits_each_stop_exactly():
    stops = [(0.0, "#000000"), (0.25, "#ff0000"), (1.0, "#0000ff")]
    assert color_math.interpolate_stops(stops, 0.0) == "#000000"
    assert color_math.interpolate_stops(stops, 0.25) == "#ff0000"
    assert color_math.interpolate_stops(stops, 1.0) == "#0000ff"
    assert color_math.interpolate_stops(stops, -1.0) == "#000000"  # clamped
    assert color_math.interpolate_stops(stops, 2.0) == "#0000ff"


# ----------------------------------------------------------- bivariate sex ratio
def _rows():
    return [
        {"iso3": "AAA", "density": 1.0, "male": 52.0},     # sparse, more men
        {"iso3": "BBB", "density": 10.0, "male": 48.0},    # mid, more women
        {"iso3": "CCC", "density": 100.0, "male": 50.01},  # dense, ~equal
        {"iso3": "DDD", "density": None, "male": 51.0},    # no density
        {"iso3": "EEE", "density": 100.0, "male": 47.0},   # dense, more women
    ]


def _bivariate(**overrides):
    options = {"ratio_column": "male", "value_column": "density"}
    options.update(overrides)
    return SexRatioBivariateScale(**options)


BLUE = color_math.hsl_to_hex(212, 1.0, 0.5)
RED = color_math.hsl_to_hex(0, 1.0, 0.5)


def test_bivariate_tints_from_white_to_full_colour_by_density():
    fills = _bivariate().paint(_rows()).fills
    assert fills[0] == color_math.lerp_hex("#ffffff", BLUE, 0.1)   # men, lowest density → almost white
    assert fills[1] == color_math.lerp_hex("#ffffff", RED, 0.55)   # women, mid density
    assert fills[4] == RED                                          # women, highest density → full red


def test_bivariate_tie_is_neutral_and_missing_density_is_no_data():
    painting = _bivariate().paint(_rows())
    assert painting.fills[2] == "#9e9e9e"
    assert painting.fills[3] is None


def test_bivariate_moves_away_from_white_as_density_grows():
    rows = [{"density": value, "male": 55.0} for value in (1, 3, 9, 27, 81)]
    fills = _bivariate().paint(rows).fills
    red_channels = [color_math.hex_to_rgb(fill)[0] for fill in fills]  # white → blue drains red
    assert red_channels == sorted(red_channels, reverse=True)
    assert len(set(fills)) == 5


def test_bivariate_legend_bars_run_from_near_white_to_full_colour():
    bars = _bivariate().paint(_rows()).legend.bars
    assert bars[0].stops == ((0.0, color_math.lerp_hex("#ffffff", BLUE, 0.1)), (1.0, BLUE))
    assert bars[1].stops[-1] == (1.0, RED)


def test_bivariate_legend_ticks_are_in_real_units():
    legend = _bivariate(value_label="people/km²").paint(_rows()).legend
    assert [bar.label for bar in legend.bars] == ["More men than women", "More women than men"]
    assert [tick.label for tick in legend.bars[0].ticks] == ["1.0", "10", "100"]
    # "No data" is added by the map writer, which owns the no-data colour.
    assert [swatch.label for swatch in legend.swatches] == ["≈ equal"]
    assert "people/km²" in legend.title


def test_bivariate_rejects_bad_saturation_range():
    with pytest.raises(ConfigError):
        _bivariate(saturation_range=[0.5, 0.2])


def test_bivariate_empty_rows_paint_nothing():
    painting = _bivariate().paint([])
    assert painting.fills == ()
    assert painting.legend.bars  # legend still renders


# ------------------------------------------------------------- spectral density
def test_spectral_extremes_and_average():
    rows = [{"density": value} for value in (1.0, 10.0, 100.0)]
    fills = SpectralDensityScale(value_column="density").paint(rows).fills
    assert fills[0] == "#08306b"   # dark blue — lowest
    assert fills[1] == "#2e9e44"   # green — exactly the (log) average
    assert fills[2] == "#d7191c"   # red — highest


def test_spectral_stop_positions_follow_center():
    scale = SpectralDensityScale(value_column="density")
    positions = [position for position, _ in scale.stops_for_center(0.4)]
    assert positions == pytest.approx([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    colors = [color for _, color in scale.stops_for_center(0.4)]
    assert colors == list(SPECTRAL_DEFAULT_COLORS)


def test_spectral_median_center_moves_green():
    rows = [{"density": value} for value in (1.0, 2.0, 3.0, 1000.0)]
    mean_fills = SpectralDensityScale(value_column="density", center="mean").paint(rows).fills
    median_fills = SpectralDensityScale(value_column="density", center="median").paint(rows).fills
    assert mean_fills != median_fills


def test_spectral_all_equal_and_missing_values():
    fills = SpectralDensityScale(value_column="density").paint(
        [{"density": 5.0}, {"density": 5.0}, {"density": None}]
    ).fills
    assert fills[0] == fills[1] == "#2e9e44"
    assert fills[2] is None


def test_spectral_custom_colors_must_be_six():
    with pytest.raises(ConfigError):
        SpectralDensityScale(value_column="density", colors=["#000000"])


def test_spectral_legend_ticks_min_average_max():
    legend = SpectralDensityScale(value_column="density").paint(
        [{"density": value} for value in (1.0, 10.0, 100.0)]
    ).legend
    assert [tick.label for tick in legend.bars[0].ticks] == ["1.0", "10", "100"]


# --------------------------------------------------------------------- registry
def test_both_scales_registered_and_resolvable():
    assert {"sex-ratio-bivariate", "spectral-density"} <= set(COLOR_SCALE_REGISTRY)
    scale = resolve_color_scale({"type": "spectral-density", "value_column": "density"})
    assert isinstance(scale, SpectralDensityScale)


def test_unknown_scale_names_itself():
    with pytest.raises(UnknownStrategyError) as info:
        resolve_color_scale({"type": "rainbow-unicorn"})
    assert "rainbow-unicorn" in str(info.value)


# ------------------------------------------------- overpopulation threshold
def test_spectral_saturate_above_makes_everything_at_threshold_red():
    rows = [{"density": value} for value in (1.0, 10.0, 1000.0, 20000.0)]
    fills = SpectralDensityScale(value_column="density", saturate_above=1000).paint(rows).fills
    assert fills[0] == "#08306b"
    assert fills[2] == fills[3] == "#d7191c"


def test_spectral_saturate_above_accepts_string_from_env():
    fills = SpectralDensityScale(value_column="density", saturate_above="100").paint(
        [{"density": 1.0}, {"density": 150.0}]
    ).fills
    assert fills[1] == "#d7191c"


def test_spectral_threshold_legend_reads_at_least():
    legend = SpectralDensityScale(value_column="density", saturate_above=1000).paint(
        [{"density": value} for value in (1.0, 10.0, 5000.0)]
    ).legend
    assert legend.bars[0].ticks[-1].label == "≥ 1,000"
    assert "≥ 1,000" in legend.bars[0].label


def test_spectral_rejects_non_positive_threshold_on_log_scale():
    with pytest.raises(ConfigError):
        SpectralDensityScale(value_column="density", saturate_above=0)
