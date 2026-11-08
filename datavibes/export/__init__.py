"""Exporter + format writers."""

from datavibes.export.exporter import Exporter

# Importing the writers module registers every built-in writer (side effect).
from datavibes.export import writers as _writers
from datavibes.export import svg_small_multiples as _svg_small_multiples
from datavibes.export import xlsx_writer as _xlsx_writer

_ = (_writers, _svg_small_multiples, _xlsx_writer)

__all__ = ["Exporter"]
