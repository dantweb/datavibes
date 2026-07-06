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


def ratio(numerator: Sequence[Number], denominator: Sequence[Number]) -> list[Number]:
    """Elementwise ``numerator / denominator``; ``None`` on null or zero divisor."""
    _require_equal_length(numerator, denominator, "ratio")
    result: list[Number] = []
    for top, bottom in zip(numerator, denominator):
        if top is None or bottom is None or bottom == 0:
            result.append(None)
        else:
            result.append(float(top) / float(bottom))
    return result


def share(part: Sequence[Number], whole: Sequence[Number]) -> list[Number]:
    """Part as a **percent** of the whole; ``None`` on null or zero whole."""
    return [None if value is None else value * 100.0 for value in ratio(part, whole)]


def penetration(part: Sequence[Number], whole: Sequence[Number]) -> list[Number]:
    """Alias of :func:`share` — percent of a whole (renewable %, EV %, …)."""
    return share(part, whole)


def cagr(series: Sequence[Number], years: int = 1) -> list[Number]:
    """Compound annual growth rate over a trailing ``years`` lag, as a percent.

    ``None`` until the lag fills, on a missing endpoint, or on a non-positive
    starting value (growth rate undefined).
    """
    if years < 1:
        raise ValueError("cagr years must be >= 1")
    result: list[Number] = []
    for index in range(len(series)):
        if index < years:
            result.append(None)
            continue
        start = series[index - years]
        end = series[index]
        if start is None or end is None or start <= 0 or end < 0:
            result.append(None)
            continue
        result.append(((float(end) / float(start)) ** (1.0 / years) - 1.0) * 100.0)
    return result


def corr(series_a: Sequence[Number], series_b: Sequence[Number]) -> list[Number]:
    """Static Pearson correlation of the whole pair, broadcast to every row.

    Every position holds the single correlation of the present pairs, so a
    grouped ``derive`` yields one correlation per group. ``None`` (everywhere)
    on fewer than two pairs or a zero-variance series.
    """
    _require_equal_length(series_a, series_b, "corr")
    value = _pearson(series_a, series_b)
    return [value for _ in series_a]


def minmax_normalize(
    series: Sequence[Number], invert: bool = False
) -> list[Number]:
    """Min-max scale present values to ``[0, 1]``; ``None`` stays ``None``.

    ``invert=True`` flips the scale (``1 - x``) — used so a *lower* price yields
    a *higher* price/performance index. An all-equal series maps to ``0.5``.
    """
    present = [float(value) for value in series if value is not None]
    if not present:
        return [None for _ in series]
    low, high = min(present), max(present)
    span = high - low
    result: list[Number] = []
    for value in series:
        if value is None:
            result.append(None)
            continue
        scaled = 0.5 if span == 0 else (float(value) - low) / span
        result.append(1.0 - scaled if invert else scaled)
    return result


def volatility(series: Sequence[Number], window: int) -> list[Number]:
    """Trailing sample standard deviation over ``window`` values.

    ``None`` until the window holds at least two present values.
    """
    if window < 2:
        raise ValueError("volatility window must be >= 2")
    result: list[Number] = []
    for index in range(len(series)):
        if index + 1 < window:
            result.append(None)
            continue
        segment = [
            float(value)
            for value in series[index + 1 - window : index + 1]
            if value is not None
        ]
        result.append(_stddev(segment))
    return result


def _stddev(values: Sequence[float]) -> Number:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return variance**0.5


def _require_equal_length(
    series_a: Sequence[Number], series_b: Sequence[Number], name: str
) -> None:
    if len(series_a) != len(series_b):
        raise ValueError(f"{name} requires equal-length series")


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
