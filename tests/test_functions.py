"""S04/S06 — pure derive helpers, tested directly with fixtures."""

import math

from datavibes.processing.functions import (
    anomaly,
    pct_change,
    rolling_avg,
    rolling_corr,
    yoy,
)


def test_pct_change_first_is_none_and_ratio():
    assert pct_change([100.0, 150.0, 75.0]) == [None, 0.5, -0.5]


def test_pct_change_zero_denominator_guarded():
    assert pct_change([0.0, 5.0]) == [None, None]


def test_yoy_percent_over_periods():
    result = yoy([100.0, 110.0, 121.0], periods=1)
    assert result[0] is None
    assert math.isclose(result[1], 10.0)
    assert math.isclose(result[2], 10.0)


def test_rolling_avg_edges_and_window():
    result = rolling_avg([1.0, 2.0, 3.0, 4.0], window=2)
    assert result == [None, 1.5, 2.5, 3.5]


def test_anomaly_numeric_baseline():
    assert anomaly([10.0, 12.0], baseline=10.0) == [0.0, 2.0]


def test_anomaly_non_numeric_baseline_uses_mean():
    result = anomaly([2.0, 4.0, 6.0], baseline="climatology")
    assert result == [-2.0, 0.0, 2.0]


def test_rolling_corr_perfect_positive():
    result = rolling_corr([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0], window=3)
    assert result[0] is None
    assert result[1] is None
    assert math.isclose(result[2], 1.0)
    assert math.isclose(result[3], 1.0)


def test_rolling_corr_short_series_is_none():
    assert rolling_corr([1.0, 2.0], [3.0, 4.0], window=3) == [None, None]


def test_rolling_corr_zero_variance_window_is_none():
    result = rolling_corr([5.0, 5.0, 5.0], [1.0, 2.0, 3.0], window=3)
    assert result[2] is None
