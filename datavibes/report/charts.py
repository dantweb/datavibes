"""Render the dataset's declared charts to PNGs (matplotlib, optional dependency).

Each :class:`~datavibes.config.models.ChartSpec` becomes one figure written to
the report's ``charts/`` directory and later embedded in the PDF. A chart that
can't be built (missing column, no numeric data) is skipped with a warning —
never a crash. matplotlib is imported lazily so the core SDK doesn't need it.
See ``docs/charts.md`` for the config reference.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from datavibes.config.models import ChartSpec

# A restrained, professional categorical palette (ink + muted accents).
_PALETTE = ["#1b3a5b", "#7a2f1d", "#5a6b52", "#b8860b", "#4b4e6d", "#8c7355"]
_INK = "#1a1a1a"
_GRID = "#d9d4c7"
_AGG = {
    "mean": lambda values: sum(values) / len(values),
    "sum": sum,
    "min": min,
    "max": max,
    "median": lambda values: sorted(values)[len(values) // 2],
}


@dataclass
class ChartImage:
    title: str
    path: Path


def render_charts(
    charts: list[ChartSpec], rows: list[dict], charts_dir: Path
) -> list[ChartImage]:
    """Render every chart spec to ``charts_dir``; return the images that succeeded."""
    if not charts:
        return []
    try:
        import matplotlib
    except ImportError:  # pragma: no cover - optional dependency
        print("warning: charts need the optional 'matplotlib' dependency", file=sys.stderr)
        return []
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    charts_dir = Path(charts_dir)
    charts_dir.mkdir(parents=True, exist_ok=True)
    _apply_style(plt)

    images: list[ChartImage] = []
    for index, spec in enumerate(charts):
        path = charts_dir / f"{index + 1:02d}-{_slug(spec.title)}.png"
        try:
            _render_one(plt, spec, rows, path)
            images.append(ChartImage(title=spec.title, path=path))
        except Exception as error:  # degrade: skip a bad chart, keep the rest
            print(f"warning: chart '{spec.title}' skipped: {error}", file=sys.stderr)
    return images


def _render_one(plt, spec: ChartSpec, rows: list[dict], path: Path) -> None:
    data = [row for row in rows if _passes_filter(row, spec.filter)]
    figure, axis = plt.subplots(figsize=(7.2, 4.0), dpi=150)

    if spec.series:
        if not _plot_multi_series(axis, spec, data):
            plt.close(figure)
            raise ValueError("no plottable series data")
    elif spec.type == "scatter":
        xs, ys = _xy_points(data, spec)
        if not xs:
            plt.close(figure)
            raise ValueError("no numeric (x, y) points")
        axis.scatter(xs, ys, color=_PALETTE[0], s=18, alpha=0.7)
    else:
        labels, values = _aggregate(data, spec)
        labels, values = _sort_and_limit(labels, values, spec)
        if not labels:
            plt.close(figure)
            raise ValueError("no plottable data")
        if spec.type == "bar":
            axis.bar(range(len(labels)), values, color=_PALETTE[0])
            axis.set_xticks(range(len(labels)))
            axis.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        elif spec.type == "area":
            axis.fill_between(range(len(labels)), values, color=_PALETTE[0], alpha=0.25)
            axis.plot(range(len(labels)), values, color=_PALETTE[0], linewidth=1.6)
            _set_line_ticks(axis, labels)
        else:  # line
            axis.plot(range(len(labels)), values, color=_PALETTE[0], linewidth=1.8, marker="o", markersize=3)
            _set_line_ticks(axis, labels)

    axis.set_title(spec.title, loc="left", fontsize=13, color=_INK, pad=10, fontweight="bold")
    axis.set_xlabel(spec.x, fontsize=9, color=_INK)
    axis.set_ylabel(spec.y, fontsize=9, color=_INK)
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _plot_multi_series(axis, spec: ChartSpec, rows: list[dict]) -> bool:
    groups: dict[str, list[tuple]] = {}
    for row in rows:
        key = row.get(spec.series)
        x, y = row.get(spec.x), _as_float(row.get(spec.y))
        if key is None or x is None or y is None:
            continue
        groups.setdefault(str(key), []).append((x, y))
    if not groups:
        return False
    for offset, (name, points) in enumerate(sorted(groups.items())):
        points.sort(key=lambda pair: _as_float(pair[0]) if _as_float(pair[0]) is not None else 0)
        xs = [pair[0] for pair in points]
        ys = [pair[1] for pair in points]
        color = _PALETTE[offset % len(_PALETTE)]
        axis.plot(xs, ys, color=color, linewidth=1.6, marker="o", markersize=3, label=name)
    axis.legend(fontsize=8, frameon=False)
    return True


def _aggregate(rows: list[dict], spec: ChartSpec) -> tuple[list[str], list[float]]:
    reducer = _AGG.get(spec.agg or "mean", _AGG["mean"])
    buckets: dict[str, list[float]] = {}
    order: list[str] = []
    for row in rows:
        label = row.get(spec.x)
        value = _as_float(row.get(spec.y))
        if label is None or value is None:
            continue
        key = str(label)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(value)
    return order, [reducer(buckets[key]) for key in order]


def _sort_and_limit(labels, values, spec: ChartSpec):
    pairs = list(zip(labels, values))
    if spec.sort:
        by = spec.sort.get("by", spec.y)
        descending = bool(spec.sort.get("desc", False))
        key = (lambda pair: pair[1]) if by == spec.y else (lambda pair: pair[0])
        pairs.sort(key=key, reverse=descending)
    if spec.limit:
        pairs = pairs[: spec.limit]
    if not pairs:
        return [], []
    labels, values = zip(*pairs)
    return list(labels), list(values)


def _xy_points(rows: list[dict], spec: ChartSpec):
    xs, ys = [], []
    for row in rows:
        x, y = _as_float(row.get(spec.x)), _as_float(row.get(spec.y))
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    return xs, ys


def _set_line_ticks(axis, labels) -> None:
    step = max(1, len(labels) // 12)
    ticks = list(range(0, len(labels), step))
    axis.set_xticks(ticks)
    axis.set_xticklabels([labels[i] for i in ticks], rotation=45, ha="right", fontsize=8)


def _passes_filter(row: dict, criteria: dict) -> bool:
    for column, expected in criteria.items():
        if str(row.get(column)) != str(expected):
            return False
    return True


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _apply_style(plt) -> None:
    plt.rcParams.update({
        "axes.edgecolor": _INK,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": _GRID,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.family": "serif",
        "text.color": _INK,
        "xtick.color": _INK,
        "ytick.color": _INK,
    })


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "chart"
