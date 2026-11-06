"""Value objects a :class:`~datavibes.interfaces.ColorScale` returns."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegendTick:
    """A labelled mark at ``position`` (0..1) along a gradient bar."""

    position: float
    label: str


@dataclass(frozen=True)
class LegendBar:
    """One horizontal gradient bar: ascending ``(position, hex)`` stops + ticks."""

    label: str
    stops: tuple[tuple[float, str], ...]
    ticks: tuple[LegendTick, ...]


@dataclass(frozen=True)
class LegendSwatch:
    """A single flat colour with a label (e.g. "No data")."""

    label: str
    color: str


@dataclass(frozen=True)
class Legend:
    title: str
    bars: tuple[LegendBar, ...]
    swatches: tuple[LegendSwatch, ...] = ()


@dataclass(frozen=True)
class Painting:
    """Per-row fills aligned to the input rows (``None`` = no data) + legend."""

    fills: tuple[str | None, ...]
    legend: Legend


def format_quantity(value: float) -> str:
    """Compact, deterministic number label for legend ticks."""
    if value >= 100:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:.0f}"
    if value >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}"
