"""The three narrow plug-in interfaces (ISP).

Every extension point of the SDK is one of these single-method ABCs. The
pipeline depends only on these abstractions, never on a concrete provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from datavibes.context import FetchContext, RunContext
    from datavibes.schema.field import Schema


class Source(ABC):
    """Fetches raw records from somewhere public. It only fetches."""

    @abstractmethod
    def fetch(self, ctx: "FetchContext") -> Iterable[dict]:
        """Yield plain ``dict`` records; empty/failed ⇒ no records, never a crash."""


class ProcessingStep(ABC):
    """A pure transform ``list[dict] -> list[dict]``; no I/O, no clock read."""

    @abstractmethod
    def apply(self, rows: list[dict], ctx: "RunContext") -> list[dict]:
        """Return transformed rows; must not mutate ``rows`` in place."""


class Writer(ABC):
    """Serialises rows to a file in the schema's column order. It only writes."""

    @abstractmethod
    def write(self, rows: list[dict], schema: "Schema", dest: Path) -> Path:
        """Write ``rows`` to ``dest`` and return the written path."""
