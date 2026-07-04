"""Injected clock + run/fetch contexts.

Determinism requirement: the wall clock is *always* injected. Nothing in the
pipeline calls ``datetime.now()`` directly; it asks the clock on the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from datavibes.config.app_config import HttpConfig

if TYPE_CHECKING:
    from datavibes.config.models import DatasetConfig

TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M"


@runtime_checkable
class Clock(Protocol):
    """A source of the current instant — injected, never read implicitly."""

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class FixedClock:
    """A clock frozen at a fixed instant — used in tests and CI for determinism."""

    instant: datetime

    def now(self) -> datetime:
        return self.instant


class SystemClock:
    """The real wall clock — the only place production reads ``datetime.now``."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def format_timestamp(instant: datetime) -> str:
    """Render an instant as the ``YYYY-MM-DD-HH-MM`` snapshot stamp."""
    return instant.strftime(TIMESTAMP_FORMAT)


@dataclass
class FetchContext:
    """What a :class:`~datavibes.interfaces.Source` needs to fetch records."""

    config: "DatasetConfig"
    clock: Clock
    http: Any = None
    http_settings: HttpConfig = field(default_factory=HttpConfig)


@dataclass
class RunContext:
    """What a :class:`~datavibes.interfaces.ProcessingStep` needs to transform."""

    config: "DatasetConfig"
    clock: Clock
    extras: dict = field(default_factory=dict)
