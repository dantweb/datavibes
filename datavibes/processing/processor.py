"""``Processor`` — folds the declared steps over the rows in order."""

from __future__ import annotations

from datavibes.config.models import DatasetConfig
from datavibes.context import Clock, RunContext
from datavibes.errors import DatavibesError
from datavibes.registry import resolve_step


class Processor:
    """Sequences processing steps; each step is a pure transform."""

    def __init__(self, clock: Clock):
        self.clock = clock

    def process(self, config: DatasetConfig, rows: list[dict]) -> list[dict]:
        ctx = RunContext(config=config, clock=self.clock)
        current = [dict(row) for row in rows]
        for spec in config.processing:
            step = resolve_step(spec)
            try:
                current = step.apply(current, ctx)
            except DatavibesError:
                raise
            except Exception as error:
                raise DatavibesError(
                    f"step '{spec.name}' failed: {error}"
                ) from error
        return current
