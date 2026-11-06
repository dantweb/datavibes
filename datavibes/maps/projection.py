"""Map projections — pure ``(lon°, lat°) -> (x, y)`` functions.

Two are enough for now: ``equal-earth`` (equal-area, the right choice for a
world density choropleth) and ``equirectangular`` (with a standard parallel, for
country/region extents). A plain dict, not a registry — two entries don't
justify one.
"""

from __future__ import annotations

import math
from typing import Callable

from datavibes.errors import ConfigError

Projection = Callable[..., tuple[float, float]]

# Equal Earth constants — Šavrič, Patterson & Jenny (2018).
_A1, _A2, _A3, _A4 = 1.340264, -0.081106, 0.000893, 0.003796
_M = math.sqrt(3.0) / 2.0


def equirectangular(
    lon: float, lat: float, standard_parallel: float = 0.0
) -> tuple[float, float]:
    """Plate carrée, x scaled by ``cos(standard_parallel)`` to keep shapes honest."""
    return (
        math.radians(lon) * math.cos(math.radians(standard_parallel)),
        math.radians(lat),
    )


def equal_earth(lon: float, lat: float, standard_parallel: float = 0.0) -> tuple[float, float]:
    """Equal Earth (equal-area pseudocylindrical). ``standard_parallel`` is ignored."""
    theta = math.asin(_M * math.sin(math.radians(lat)))
    theta2 = theta * theta
    theta6 = theta2 * theta2 * theta2
    x = (
        math.radians(lon)
        * math.cos(theta)
        / (_M * (_A1 + 3 * _A2 * theta2 + theta6 * (7 * _A3 + 9 * _A4 * theta2)))
    )
    y = theta * (_A1 + _A2 * theta2 + theta6 * (_A3 + _A4 * theta2))
    return x, y


PROJECTIONS: dict[str, Projection] = {
    "equal-earth": equal_earth,
    "equirectangular": equirectangular,
}


def resolve_projection(name: str) -> Projection:
    projection = PROJECTIONS.get(name)
    if projection is None:
        raise ConfigError(
            f"unknown projection '{name}' (known: {', '.join(sorted(PROJECTIONS))})"
        )
    return projection
