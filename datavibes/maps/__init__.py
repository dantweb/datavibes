"""Map framework (S13) — colour scales, geometry, projections, SVG rendering.

Importing this package registers the built-in colour scales (side effect).
"""

from datavibes.maps import color_scales as _builtin_color_scales
from datavibes.maps import svg_writer as _builtin_svg_writer

_ = (_builtin_color_scales, _builtin_svg_writer)
