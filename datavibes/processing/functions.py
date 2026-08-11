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


def add(series_a: Sequence[Number], series_b: Sequence[Number]) -> list[Number]:
    """Elementwise ``a + b``; ``None`` wherever either side is missing.

    The additive partner of :func:`ratio` — composite gauges that sum two rates
    (a misery index, a combined-risk total) need it and nothing else does it.
    """
    _require_equal_length(series_a, series_b, "add")
    return [
        None if left is None or right is None else float(left) + float(right)
        for left, right in zip(series_a, series_b)
    ]


def subtract(series_a: Sequence[Number], series_b: Sequence[Number]) -> list[Number]:
    """Elementwise ``a - b``; ``None`` wherever either side is missing.

    The gap between two measured levels (renewable share minus its weather-
    dependent portion, total cost minus its wage component) is a column
    customers ask for and no ratio expresses.
    """
    _require_equal_length(series_a, series_b, "subtract")
    return [
        None if left is None or right is None else float(left) - float(right)
        for left, right in zip(series_a, series_b)
    ]


def share_of_total(series: Sequence[Number]) -> list[Number]:
    """Each element as a **percent** of the series total — market share.

    The partner of :func:`hhi` and :func:`gini`: those describe how concentrated
    a cohort is, this says which member holds what. Unlike :func:`share` there is
    no second series — the denominator is the column's own sum, so a grouped
    ``derive`` yields shares within each group. ``None`` on a non-positive total.
    """
    present = [float(value) for value in series if value is not None]
    total = sum(present)
    if not present or total <= 0:
        return [None for _ in series]
    return [None if value is None else float(value) / total * 100.0 for value in series]


def gini(series: Sequence[Number]) -> list[Number]:
    """Gini coefficient of the present values, broadcast to every row.

    ``0`` = perfect equality, approaching ``1`` = one holder takes everything.
    Like :func:`corr` this is a whole-series statistic, so a grouped ``derive``
    yields one coefficient per group. ``None`` everywhere when nothing is
    present or the values sum to zero (inequality undefined).
    """
    present = sorted(float(value) for value in series if value is not None)
    total = sum(present)
    if not present or total <= 0:
        return [None for _ in series]
    count = len(present)
    weighted = sum((index + 1) * value for index, value in enumerate(present))
    coefficient = (2.0 * weighted) / (count * total) - (count + 1.0) / count
    return [coefficient for _ in series]


def hhi(series: Sequence[Number]) -> list[Number]:
    """Herfindahl-Hirschman concentration index of the present values (0-1).

    Each value becomes its share of the total; the index is the sum of squared
    shares — ``1`` for a monopoly, ``1/n`` for ``n`` equal players. Broadcast to
    every row, so a grouped ``derive`` yields one index per group (e.g. supplier
    concentration per contracting authority). ``None`` on a non-positive total.
    """
    present = [float(value) for value in series if value is not None]
    total = sum(present)
    if not present or total <= 0:
        return [None for _ in series]
    index = sum((value / total) ** 2 for value in present)
    return [index for _ in series]


def zscore(series: Sequence[Number]) -> list[Number]:
    """Standardize each element as ``(x - mean) / stddev`` of the present values.

    ``None`` stays ``None``; a zero-variance series yields ``None`` everywhere
    (standardization undefined).
    """
    present = [float(value) for value in series if value is not None]
    mean = _mean(present)
    deviation = _stddev(present)
    if mean is None or deviation is None or deviation == 0:
        return [None for _ in series]
    return [None if value is None else (float(value) - mean) / deviation for value in series]


def seasonal_index(series: Sequence[Number], period: int) -> list[Number]:
    """Seasonal index of each element's phase — phase mean ÷ grand mean.

    With ``period=12`` on a monthly series every January row carries the same
    index: ``1.2`` means Januaries run 20% above the annual average. ``None``
    where the phase or the grand mean has no present values.
    """
    if period < 2:
        raise ValueError("seasonal_index period must be >= 2")
    grand_mean = _mean(series)
    if grand_mean is None or grand_mean == 0:
        return [None for _ in series]
    phase_means: dict[int, Number] = {}
    for phase in range(period):
        phase_means[phase] = _mean(series[phase::period])
    result: list[Number] = []
    for index in range(len(series)):
        phase_mean = phase_means[index % period]
        result.append(None if phase_mean is None else phase_mean / grand_mean)
    return result


def linear_forecast(
    series: Sequence[Number], horizon: int = 1, window: int = 5
) -> list[Number]:
    """Project each row ``horizon`` steps ahead from a trailing least-squares fit.

    The fit uses the up-to-``window`` trailing values (positions as the x axis),
    so the projection at row ``i`` is the trend line evaluated at ``i +
    horizon``. ``None`` until the window fills or when it holds fewer than two
    present values (a slope needs two points).
    """
    if horizon < 1:
        raise ValueError("linear_forecast horizon must be >= 1")
    if window < 2:
        raise ValueError("linear_forecast window must be >= 2")
    result: list[Number] = []
    for index in range(len(series)):
        if index + 1 < window:
            result.append(None)
            continue
        points = [
            (float(offset), float(value))
            for offset, value in enumerate(series[index + 1 - window : index + 1])
            if value is not None
        ]
        result.append(_project(points, float(window - 1 + horizon)))
    return result


def _project(points: Sequence[tuple[float, float]], at: float) -> Number:
    if len(points) < 2:
        return None
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    variance_x = sum((x - mean_x) ** 2 for x, _ in points)
    if variance_x == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance_x
    return mean_y + slope * (at - mean_x)


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
