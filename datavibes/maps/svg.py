"""Pure SVG fragment builders — rings → path data, legend → markup.

No I/O. Numbers are rounded to one decimal and ``-0.0`` is normalised so the
same geometry always serialises to the same bytes.
"""

from __future__ import annotations

from typing import Iterable, Sequence
from xml.sax.saxutils import escape, quoteattr

from datavibes.maps.painting import Legend, LegendSwatch

Point = tuple[float, float]

LEGEND_BAR_WIDTH = 320.0
LEGEND_BAR_HEIGHT = 12.0
LEGEND_ROW_HEIGHT = 46.0
SWATCH_SIZE = 12.0
TEXT_COLOR = "#333333"
FONT = "font-family=\"Helvetica, Arial, sans-serif\""


def number(value: float) -> str:
    text = f"{value:.1f}"
    return "0.0" if text == "-0.0" else text


def text(value: object) -> str:
    return escape(str(value))


def attr(value: object) -> str:
    return quoteattr(str(value))


def ring_path(points: Sequence[Point]) -> str:
    """``M x y L x y … Z`` with consecutive duplicate points (after rounding) dropped."""
    commands: list[str] = []
    previous: tuple[str, str] | None = None
    for x, y in points:
        current = (number(x), number(y))
        if current == previous:
            continue
        commands.append(("M" if not commands else "L") + f"{current[0]} {current[1]}")
        previous = current
    if len(commands) < 3:
        return ""
    return "".join(commands) + "Z"


def legend_markup(
    legend: Legend,
    extra_swatches: Iterable[LegendSwatch],
    left: float,
    top: float,
) -> tuple[list[str], list[str], float]:
    """Return ``(defs, body, height)`` for the legend placed at ``(left, top)``."""
    defs: list[str] = []
    body: list[str] = [
        f'<text x="{number(left)}" y="{number(top + 12)}" font-size="13" '
        f'font-weight="bold" fill="{TEXT_COLOR}">{text(legend.title)}</text>'
    ]
    cursor = top + 24
    for index, bar in enumerate(legend.bars):
        gradient_id = f"legend-bar-{index}"
        stops = "".join(
            f'<stop offset="{number(position * 100)}%" stop-color="{color}"/>'
            for position, color in bar.stops
        )
        defs.append(f'<linearGradient id="{gradient_id}" x1="0" x2="1" y1="0" y2="0">{stops}</linearGradient>')
        body.append(
            f'<text x="{number(left)}" y="{number(cursor + 10)}" font-size="11" '
            f'fill="{TEXT_COLOR}">{text(bar.label)}</text>'
        )
        bar_top = cursor + 14
        body.append(
            f'<rect x="{number(left)}" y="{number(bar_top)}" width="{number(LEGEND_BAR_WIDTH)}" '
            f'height="{number(LEGEND_BAR_HEIGHT)}" fill="url(#{gradient_id})" stroke="#999999" stroke-width="0.5"/>'
        )
        for tick in bar.ticks:
            x = left + tick.position * LEGEND_BAR_WIDTH
            body.append(
                f'<line x1="{number(x)}" y1="{number(bar_top + LEGEND_BAR_HEIGHT)}" '
                f'x2="{number(x)}" y2="{number(bar_top + LEGEND_BAR_HEIGHT + 4)}" stroke="{TEXT_COLOR}" stroke-width="0.8"/>'
            )
            body.append(
                f'<text x="{number(x)}" y="{number(bar_top + LEGEND_BAR_HEIGHT + 15)}" font-size="10" '
                f'text-anchor="middle" fill="{TEXT_COLOR}">{text(tick.label)}</text>'
            )
        cursor += LEGEND_ROW_HEIGHT
    swatch_x = left
    swatches = list(legend.swatches) + list(extra_swatches)
    for swatch in swatches:
        body.append(
            f'<rect x="{number(swatch_x)}" y="{number(cursor)}" width="{number(SWATCH_SIZE)}" '
            f'height="{number(SWATCH_SIZE)}" fill="{swatch.color}" stroke="#999999" stroke-width="0.5"/>'
        )
        body.append(
            f'<text x="{number(swatch_x + SWATCH_SIZE + 5)}" y="{number(cursor + 10)}" font-size="11" '
            f'fill="{TEXT_COLOR}">{text(swatch.label)}</text>'
        )
        swatch_x += SWATCH_SIZE + 5 + 7 * len(swatch.label) + 20
    if swatches:
        cursor += SWATCH_SIZE + 8
    return defs, body, cursor - top
