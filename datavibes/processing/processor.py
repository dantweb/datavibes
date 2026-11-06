"""``Processor`` — folds the declared steps over the rows in order."""

from __future__ import annotations

from datavibes.config.models import DatasetConfig
from datavibes.context import Clock, RunContext
from datavibes.errors import DatavibesError
from datavibes.provenance import Exclusion, Provenance
from datavibes.registry import resolve_step


class Processor:
    """Sequences processing steps; each step is a pure transform."""

    def __init__(self, clock: Clock):
        self.clock = clock

    def process(self, config: DatasetConfig, rows: list[dict]) -> list[dict]:
        return self.process_with_provenance(config, rows)[0]

    def process_with_provenance(
        self, config: DatasetConfig, rows: list[dict]
    ) -> tuple[list[dict], Provenance]:
        """Like :meth:`process`, also counting rows removed by reasoned steps.

        A step that declares ``exclusion_reason`` (e.g. ``filter``) is recorded
        with the number of rows it dropped.
        """
        ctx = RunContext(config=config, clock=self.clock)
        current = [dict(row) for row in rows]
        exclusions: list[Exclusion] = []
        for spec in config.processing:
            step = resolve_step(spec)
            before = len(current)
            try:
                current = step.apply(current, ctx)
            except DatavibesError:
                raise
            except Exception as error:
                raise DatavibesError(
                    f"step '{spec.name}' failed: {error}"
                ) from error
            reason = getattr(step, "exclusion_reason", None)
            if reason is not None and before > len(current):
                exclusions.append(Exclusion(reason, before - len(current)))
        return current, Provenance(exclusions=tuple(exclusions))
