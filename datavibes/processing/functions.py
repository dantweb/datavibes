"""Pure derive helpers — each a testable ``series -> series`` function.

Every helper takes one or more numeric series (``list`` of ``float | None``)
and returns a list of the same length aligned to the input rows. Undefined
positions (start of a window, zero denominator, zero variance) yield ``None``.
No helper reads the clock, the network, or disk.
"""

from __future__ import annotations

from typing import Optional, Sequence

Number = Optional[float]


def pct_change(series: Sequence[Number]) -> list[Number]:
    """Fractional change vs. the previous element; first element is ``None``."""
    result: list[Number] = [None]
    for index in range(1, len(series)):
        previous = series[index - 1]
        current = series[index]
        result.append(_ratio_change(previous, current))
    return result


def yoy(series: Sequence[Number], periods: int = 1) -> list[Number]:
    """Percent change over a ``periods`` lag (year-over-year), scaled ×100."""
    if periods < 1:
        raise ValueError("yoy periods must be >= 1")
    result: list[Number] = []
    for index in range(len(series)):
        if index < periods:
            result.append(None)
            continue
        change = _ratio_change(series[index - periods], series[index])
        result.append(None if change is None else change * 100.0)
    return result


def rolling_avg(series: Sequence[Number], window: int) -> list[Number]:
    """Trailing mean over ``window`` elements; ``None`` until the window fills."""
    if window < 1:
        raise ValueError("rolling_avg window must be >= 1")
    result: list[Number] = []
    for index in range(len(series)):
        if index + 1 < window:
            result.append(None)
            continue
        segment = series[index + 1 - window : index + 1]
        result.append(_mean(segment))
    return result


def anomaly(series: Sequence[Number], baseline: object = None) -> list[Number]:
    """Deviation of each element from a baseline.

    A numeric ``baseline`` subtracts that constant; any non-numeric baseline
    (or ``None``) subtracts the mean of the present values.
    """
    if isinstance(baseline, (int, float)) and not isinstance(baseline, bool):
        reference: Number = float(baseline)
    else:
        reference = _mean(series)
    result: list[Number] = []
    for value in series:
        if value is None or reference is None:
            result.append(None)
        else:
            result.append(float(value) - reference)
    return result


def rolling_corr(
    series_a: Sequence[Number], series_b: Sequence[Number], window: int
) -> list[Number]:
    """Trailing Pearson correlation over ``window`` pairs.

    ``None`` until the window fills; a zero-variance window yields ``None``.
    """
    if window < 2:
        raise ValueError("rolling_corr window must be >= 2")
    if len(series_a) != len(series_b):
        raise ValueError("rolling_corr requires equal-length series")
    result: list[Number] = []
    for index in range(len(series_a)):
        if index + 1 < window:
            result.append(None)
            continue
        window_a = series_a[index + 1 - window : index + 1]
        window_b = series_b[index + 1 - window : index + 1]
        result.append(_pearson(window_a, window_b))
    return result


def _ratio_change(previous: Number, current: Number) -> Number:
    if previous is None or current is None or previous == 0:
        return None
    return (current - previous) / previous


def _mean(values: Sequence[Number]) -> Number:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _pearson(values_a: Sequence[Number], values_b: Sequence[Number]) -> Number:
    pairs = [
        (float(a), float(b))
        for a, b in zip(values_a, values_b)
        if a is not None and b is not None
    ]
    if len(pairs) < 2:
        return None
    mean_a = sum(a for a, _ in pairs) / len(pairs)
    mean_b = sum(b for _, b in pairs) / len(pairs)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in pairs)
    variance_a = sum((a - mean_a) ** 2 for a, _ in pairs)
    variance_b = sum((b - mean_b) ** 2 for _, b in pairs)
    if variance_a == 0 or variance_b == 0:
        return None
    return covariance / ((variance_a * variance_b) ** 0.5)
