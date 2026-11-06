"""Pure colour arithmetic — HSL → hex, hex interpolation, colour stops.

Every channel is rounded half-up to an integer so the same inputs always yield
the same hex string (determinism, Req 7).
"""

from __future__ import annotations

import colorsys
from typing import Sequence

ColorStop = tuple[float, str]


def hsl_to_hex(hue_degrees: float, saturation: float, lightness: float) -> str:
    """``HSL(hue°, s, l)`` with ``s``/``l`` in ``[0, 1]`` → ``#rrggbb``."""
    red, green, blue = colorsys.hls_to_rgb((hue_degrees % 360) / 360.0, lightness, saturation)
    return rgb_to_hex((_channel(red), _channel(green), _channel(blue)))


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    text = color.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected #rrggbb, got {color!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def rgb_to_hex(rgb: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(value))):02x}" for value in rgb)


def lerp_hex(start: str, end: str, fraction: float) -> str:
    """Linear sRGB interpolation between two hex colours."""
    fraction = max(0.0, min(1.0, fraction))
    start_rgb, end_rgb = hex_to_rgb(start), hex_to_rgb(end)
    return rgb_to_hex(
        tuple(
            int(a + (b - a) * fraction + 0.5) for a, b in zip(start_rgb, end_rgb)
        )
    )


def interpolate_stops(stops: Sequence[ColorStop], position: float) -> str:
    """Colour at ``position`` along ascending ``(position, hex)`` stops (clamped)."""
    if not stops:
        raise ValueError("at least one colour stop is required")
    if position <= stops[0][0]:
        return stops[0][1]
    for (left_pos, left_color), (right_pos, right_color) in zip(stops, stops[1:]):
        if position <= right_pos:
            span = right_pos - left_pos
            fraction = 0.0 if span == 0 else (position - left_pos) / span
            return lerp_hex(left_color, right_color, fraction)
    return stops[-1][1]


def _channel(unit_value: float) -> int:
    return int(unit_value * 255 + 0.5)
