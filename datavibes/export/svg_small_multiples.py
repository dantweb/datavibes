"""``svg-small-multiples`` — one time-series panel per entity, on shared axes.

Why facets: past about eight series a single chart cannot give every line its
own distinguishable hue, so each entity gets its own panel. In each panel the
entity is the one coloured line, every other entity is drawn behind it in grey
for context, and both axes are shared, so panels compare by position alone.

* ``x`` (time), ``y`` (value) and ``facet`` (entity) are column names;
* ``x_range`` pins the x axis (e.g. ``[1950, 2025]``), so empty years read as
  gaps instead of being cropped away;
* ``y_scale: log`` suits values spanning orders of magnitude;
* ``basis_column`` + ``estimated``: segments touching an estimated row are dashed;
* ``reference_y``: a second column drawn as a thin dark line in each panel
  (e.g. the all-population value behind a sub-population's line);
* ``show_empty``: panels for ``facet_order`` entries without data, saying so;
* every point carries a native ``<title>`` tooltip, and each panel labels its
  latest value directly.

Pure SVG with a light/dark ``<style>``, no dependencies; numbers are rounded so
the output is byte-stable for golden tests.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from datavibes.errors import ConfigError
from datavibes.interfaces import Writer
from datavibes.maps.svg import attr, number, text
from datavibes.registry import register_writer
from datavibes.schema.field import Schema

STYLE = """
.surface{fill:#fcfcfb}.ink{fill:#0b0b0b}.muted{fill:#52514e}
.grid{stroke:#e6e4dd;stroke-width:1}.axis{stroke:#b5b3ab;stroke-width:1}
.context{stroke:#cfcdc6;stroke-width:1;fill:none}
.focus{stroke:#2a78d6;stroke-width:2;fill:none;stroke-linejoin:round;stroke-linecap:round}
.reference{stroke:#7d7b74;stroke-width:1.25;fill:none}
.estimated{stroke-dasharray:4 3}.dot{fill:#2a78d6}.hit{fill:transparent}
@media (prefers-color-scheme: dark){
.surface{fill:#1a1a19}.ink{fill:#f0efec}.muted{fill:#c3c2b7}
.grid{stroke:#2e2d2a}.axis{stroke:#5b5a55}.context{stroke:#45443f}
.focus{stroke:#3987e5}.reference{stroke:#a3a198}.dot{fill:#3987e5}}
""".strip()
FONT = 'font-family="Helvetica, Arial, sans-serif"'
MARGIN = 24.0
HEADER = 92.0
PANEL_GAP = 18.0
AXIS_LEFT = 44.0
AXIS_BOTTOM = 20.0
PANEL_TITLE = 22.0


@register_writer("svg-small-multiples")
class SvgSmallMultiplesWriter(Writer):
    extension = "svg"

    def __init__(
        self,
        x: str,
        y: str,
        facet: str,
        title: str = "",
        subtitle: str = "",
        y_label: str = "",
        footer: Sequence[str] = (),
        x_range: Sequence[float] | None = None,
        y_scale: str = "linear",
        facet_order: Sequence[str] | None = None,
        basis_column: str | None = None,
        estimated: Sequence[str] = (),
        columns: int = 4,
        panel_width: float = 280.0,
        panel_height: float = 170.0,
        unit: str = "",
        reference_y: str | None = None,
        reference_label: str = "",
        show_empty: bool = False,
        empty_note: str = "no data",
    ):
        if not (x and y and facet):
            raise ConfigError("svg-small-multiples requires 'x', 'y' and 'facet'")
        if y_scale not in ("linear", "log"):
            raise ConfigError("svg-small-multiples: y_scale must be 'linear' or 'log'")
        if x_range is not None and (len(x_range) != 2 or x_range[0] >= x_range[1]):
            raise ConfigError("svg-small-multiples: x_range must be [low, high]")
        self.x, self.y, self.facet = x, y, facet
        self.title, self.subtitle, self.y_label = title, subtitle, y_label
        self.footer = list(footer)
        self.x_range = tuple(float(v) for v in x_range) if x_range else None
        self.log = y_scale == "log"
        self.facet_order = list(facet_order or [])
        self.basis_column = basis_column
        self.estimated = set(estimated)
        self.columns = max(1, int(columns))
        self.panel_width, self.panel_height = float(panel_width), float(panel_height)
        self.unit = unit
        self.reference_y = reference_y
        self.reference_label = reference_label or (reference_y or "")
        self.show_empty = bool(show_empty)
        self.empty_note = empty_note

    # ------------------------------------------------------------- data
    def _series(self, rows: list[dict], column: str | None = None) -> dict[str, list[tuple[float, float, bool]]]:
        column = column or self.y
        series: dict[str, list[tuple[float, float, bool]]] = {}
        for row in rows:
            name, x, y = row.get(self.facet), row.get(self.x), row.get(column)
            if name is None or x is None or y is None:
                continue
            if self.log and float(y) <= 0:
                continue
            estimated = bool(self.basis_column) and row.get(self.basis_column) in self.estimated
            series.setdefault(str(name), []).append((float(x), float(y), estimated))
        for points in series.values():
            points.sort()
        ordered = [name for name in self.facet_order if name in series or self.show_empty]
        ordered += sorted(name for name in series if name not in ordered)
        return {name: series.get(name, []) for name in ordered}

    def _x_domain(self, series) -> tuple[float, float]:
        if self.x_range:
            return self.x_range
        xs = [x for points in series.values() for x, _, _ in points]
        return (min(xs), max(xs)) if xs else (0.0, 1.0)

    def _y_domain(self, series) -> tuple[float, float]:
        ys = [y for points in series.values() for _, y, _ in points]
        if not ys:
            return (1.0, 10.0) if self.log else (0.0, 1.0)
        if self.log:
            low, high = _log_step(min(ys), down=True), _log_step(max(ys), down=False)
            return (low, high) if high > low else (low, low * 10)  # all values equal
        return (0.0, _nice_ceiling(max(ys)))

    # ------------------------------------------------------------- render
    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.render(rows), encoding="utf-8")
        return dest

    def render(self, rows: list[dict]) -> str:
        series = self._series(rows)
        reference = self._series(rows, self.reference_y) if self.reference_y else {}
        x_domain = self._x_domain(series)
        y_domain = self._y_domain({**{f"ref:{k}": v for k, v in reference.items()}, **series})
        count = max(1, len(series))
        grid_rows = math.ceil(count / self.columns)
        cell_w = self.panel_width + PANEL_GAP
        cell_h = self.panel_height + PANEL_TITLE + AXIS_BOTTOM + PANEL_GAP
        width = MARGIN * 2 + cell_w * min(count, self.columns) - PANEL_GAP
        footer = [part for line in self.footer for part in _wrap(line, int((width - 2 * MARGIN) / 6.0))]
        footer_h = 18.0 * len(footer) + (12.0 if footer else 0.0)
        height = HEADER + cell_h * grid_rows + footer_h + MARGIN
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{number(width)}" height="{number(height)}" '
            f'viewBox="0 0 {number(width)} {number(height)}" {FONT}>',
            f"<style>{STYLE}</style>",
            f'<rect class="surface" width="{number(width)}" height="{number(height)}"/>',
        ]
        parts += self._header(width)
        for position, name in enumerate(series):
            left = MARGIN + (position % self.columns) * cell_w
            top = HEADER + (position // self.columns) * cell_h
            parts += self._panel(name, series, left, top, x_domain, y_domain, reference.get(name, []))
        line_y = HEADER + cell_h * grid_rows + 6.0
        for line in footer:
            parts.append(f'<text class="muted" x="{number(MARGIN)}" y="{number(line_y)}" font-size="11">{text(line)}</text>')
            line_y += 18.0
        parts.append("</svg>")
        return "\n".join(parts) + "\n"

    def _header(self, width: float) -> list[str]:
        parts = []
        if self.title:
            parts.append(f'<text class="ink" x="{number(MARGIN)}" y="34.0" font-size="20" font-weight="bold">{text(self.title)}</text>')
        if self.subtitle:
            parts.append(f'<text class="muted" x="{number(MARGIN)}" y="56.0" font-size="13">{text(self.subtitle)}</text>')
        # Legend: what the line styles mean (identity is the panel title, not colour).
        legend_y = 76.0
        x = MARGIN
        items = [("focus", "this country")]
        if self.estimated:
            items.append(("focus estimated", "estimated (" + ", ".join(sorted(self.estimated)) + ")"))
        if self.reference_y:
            items.append(("reference", self.reference_label))
        items.append(("context", "other countries"))
        for css, label in items:
            parts.append(f'<line class="{css}" x1="{number(x)}" y1="{number(legend_y - 4)}" x2="{number(x + 22)}" y2="{number(legend_y - 4)}"/>')
            parts.append(f'<text class="muted" x="{number(x + 28)}" y="{number(legend_y)}" font-size="11">{text(label)}</text>')
            x += 40 + 6.2 * len(label)
        if self.y_label:
            parts.append(f'<text class="muted" x="{number(width - MARGIN)}" y="{number(legend_y)}" font-size="11" text-anchor="end">'
                         f'{text(self.y_label)}{" (log scale)" if self.log else ""}</text>')
        return parts

    def _panel(self, name, series, left, top, x_domain, y_domain, reference=()) -> list[str]:
        plot_left = left + AXIS_LEFT
        plot_top = top + PANEL_TITLE
        plot_w = self.panel_width - AXIS_LEFT
        plot_h = self.panel_height

        def px(value: float) -> float:
            return plot_left + (value - x_domain[0]) / (x_domain[1] - x_domain[0]) * plot_w

        def py(value: float) -> float:
            low, high = y_domain
            if self.log:
                unit = (math.log10(value) - math.log10(low)) / (math.log10(high) - math.log10(low))
            else:
                unit = (value - low) / (high - low) if high > low else 0.0
            return plot_top + plot_h - unit * plot_h

        points = series[name]
        parts = [f'<g aria-label={attr(name)}>']
        parts.append(f'<text class="ink" x="{number(left)}" y="{number(top + 14)}" font-size="13" font-weight="bold">{text(name)}</text>')
        if points:
            last_x, last_y, _ = points[-1]
            parts.append(f'<text class="muted" x="{number(left + self.panel_width)}" y="{number(top + 14)}" '
                         f'font-size="11" text-anchor="end">{_format_x(last_x)}: {text(_compact(last_y))}</text>')
        for tick in _y_ticks(y_domain, self.log):
            y = py(tick)
            parts.append(f'<line class="grid" x1="{number(plot_left)}" y1="{number(y)}" x2="{number(plot_left + plot_w)}" y2="{number(y)}"/>')
            parts.append(f'<text class="muted" x="{number(plot_left - 4)}" y="{number(y + 3.5)}" font-size="10" text-anchor="end">{text(_compact(tick))}</text>')
        baseline = plot_top + plot_h
        parts.append(f'<line class="axis" x1="{number(plot_left)}" y1="{number(baseline)}" x2="{number(plot_left + plot_w)}" y2="{number(baseline)}"/>')
        for tick in _x_ticks(x_domain):
            x = px(tick)
            parts.append(f'<text class="muted" x="{number(x)}" y="{number(baseline + 14)}" font-size="10" text-anchor="middle">{_format_x(tick)}</text>')
        for other, other_points in series.items():
            if other != name:
                for path in _paths(other_points, px, py, split_estimated=False):
                    parts.append(f'<path class="context" d="{path[0]}"/>')
        for path, _ in _paths(list(reference), px, py, split_estimated=False):
            parts.append(f'<path class="reference" d="{path}"/>')
        if not points:
            note_w = 6.4 * len(self.empty_note) + 16
            centre_x, centre_y = plot_left + plot_w / 2, plot_top + plot_h / 2
            parts.append(f'<rect class="surface" x="{number(centre_x - note_w / 2)}" y="{number(centre_y - 13)}" '
                         f'width="{number(note_w)}" height="20" rx="4"/>')
            parts.append(f'<text class="muted" x="{number(centre_x)}" y="{number(centre_y + 1)}" '
                         f'font-size="12" text-anchor="middle">{text(self.empty_note)}</text>')
        for path, estimated in _paths(points, px, py, split_estimated=bool(self.estimated)):
            css = "focus estimated" if estimated else "focus"
            parts.append(f'<path class="{css}" d="{path}"/>')
        for x, y in _isolated(points):  # a year with no neighbour would otherwise be invisible
            parts.append(f'<circle class="dot" cx="{number(px(x))}" cy="{number(py(y))}" r="2.5"/>')
        if points:
            last_x, last_y, _ = points[-1]
            parts.append(f'<circle class="dot" cx="{number(px(last_x))}" cy="{number(py(last_y))}" r="3"/>')
        for x, y, estimated in points:
            label = f"{name} {_format_x(x)}: {_grouped(y)}{(' ' + self.unit) if self.unit else ''}"
            if estimated:
                label += " (estimated)"
            parts.append(f'<circle class="hit" cx="{number(px(x))}" cy="{number(py(y))}" r="5"><title>{text(label)}</title></circle>')
        parts.append("</g>")
        return parts


# ------------------------------------------------------------------ helpers
def _paths(points, px, py, split_estimated: bool) -> list[tuple[str, bool]]:
    """Polyline runs: broken at missing years; split by basis when ``split_estimated``."""
    runs: list[tuple[list[tuple[float, float]], bool]] = []
    for (x0, y0, e0), (x1, y1, e1) in zip(points, points[1:]):
        if x1 - x0 > 1.0:  # a missing year → a visible gap, never a bridged line
            continue
        estimated = split_estimated and (e0 or e1)
        segment = [(px(x0), py(y0)), (px(x1), py(y1))]
        if runs and runs[-1][1] == estimated and runs[-1][0][-1] == segment[0]:
            runs[-1][0].append(segment[1])
        else:
            runs.append((segment, estimated))
    return [("".join(("M" if i == 0 else "L") + f"{number(x)} {number(y)}" for i, (x, y) in enumerate(run)), est)
            for run, est in runs]


def _isolated(points) -> list[tuple[float, float]]:
    """Points with no neighbour within one x-step: they draw no line segment."""
    xs = {x for x, _, _ in points}
    return [(x, y) for x, y, _ in points[:-1]
            if not any(0 < abs(other - x) <= 1.0 for other in xs)]


def _wrap(line: str, limit: int) -> list[str]:
    """Greedy word wrap so long footer lines stay inside the canvas."""
    lines, current = [], ""
    for word in line.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def _y_ticks(domain: tuple[float, float], log: bool) -> list[float]:
    low, high = domain
    if log:
        powers = range(math.ceil(math.log10(low) - 1e-9), math.floor(math.log10(high) + 1e-9) + 1)
        return [10.0 ** power for power in powers]
    step = _nice_ceiling(high / 4) if high > 0 else 1.0
    return [step * index for index in range(0, int(round(high / step)) + 1)]


def _x_ticks(domain: tuple[float, float]) -> list[float]:
    low, high = domain
    span = high - low
    step = next((s for s in (1, 2, 5, 10, 25, 50, 100) if span / s <= 4), 250)
    first = math.ceil(low / step) * step
    ticks = []
    value = first
    while value <= high + 1e-9:
        ticks.append(float(value))
        value += step
    return ticks


def _log_step(value: float, down: bool) -> float:
    """The nearest 1/2/5 × 10ⁿ at or below (``down``) or at or above ``value``."""
    magnitude = 10 ** math.floor(math.log10(value))
    steps = [factor * magnitude for factor in (1, 2, 5, 10)]
    if down:
        return max(step for step in steps if step <= value * (1 + 1e-9))
    return min(step for step in steps if step >= value * (1 - 1e-9))


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 2.5, 5, 10):
        if value <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def _compact(value: float) -> str:
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= threshold:
            scaled = value / threshold
            return f"{scaled:.0f}{suffix}" if scaled >= 100 or scaled == int(scaled) else f"{scaled:.1f}{suffix}"
    return f"{value:.0f}" if value >= 10 or value == int(value) else f"{value:.1f}"


def _grouped(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 10 else f"{value:,.2f}"


def _format_x(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else number(value)
