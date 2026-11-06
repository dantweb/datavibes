"""Run provenance — what the pipeline left out, and why.

Filters run during processing, so a writer only ever sees the rows that
survived. ``Provenance`` carries the counts forward so an output (e.g. a map
legend) can say "3,236 shown, 781 not included: 762 no usable density …"
from the pipeline's own bookkeeping, never from a guess.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Exclusion:
    """Rows a reasoned step removed: ``count`` rows, for ``reason``."""

    reason: str
    count: int


@dataclass(frozen=True)
class Provenance:
    exclusions: tuple[Exclusion, ...] = ()

    @property
    def total_excluded(self) -> int:
        return sum(exclusion.count for exclusion in self.exclusions)

    def as_dict(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for exclusion in self.exclusions:
            merged[exclusion.reason] = merged.get(exclusion.reason, 0) + exclusion.count
        return merged
