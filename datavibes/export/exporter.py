"""``Exporter`` — places processed rows at the delivery-contract path."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from datavibes.config.models import DatasetConfig, OutputSpec
from datavibes.context import Clock
from datavibes.provenance import Provenance
from datavibes.registry import resolve_writer
from datavibes.store.filestore import FileStore

_FORMAT_EXTENSIONS = {"csv": "csv", "json": "json", "parquet": "parquet"}


class Exporter:
    """Resolves writers and writes to the output-contract path."""

    def __init__(self, store: FileStore, clock: Clock):
        self.store = store
        self.clock = clock

    def export(
        self,
        config: DatasetConfig,
        rows: list[dict],
        fmt: str = "csv",
        provenance: Provenance | None = None,
    ) -> Path:
        """Write one format (the explicit ``--format`` path)."""
        return self._write(config, rows, OutputSpec(name=fmt), self.clock.now(), provenance)

    def export_outputs(
        self,
        config: DatasetConfig,
        rows: list[dict],
        default_format: str = "csv",
        provenance: Provenance | None = None,
    ) -> list[Path]:
        """Write every declared output; all share one timestamp stem.

        A dataset without ``outputs:`` gets exactly one ``default_format`` file,
        which is the pre-S13 behaviour.
        """
        specs = config.outputs or [OutputSpec(name=default_format)]
        timestamp = self.clock.now()
        return [self._write(config, rows, spec, timestamp, provenance) for spec in specs]

    def _write(
        self,
        config: DatasetConfig,
        rows: list[dict],
        spec: OutputSpec,
        timestamp: datetime,
        provenance: Provenance | None = None,
    ) -> Path:
        writer = resolve_writer(spec.name, spec.options)
        writer.attach_provenance(provenance or Provenance())
        extension = getattr(writer, "extension", None) or _FORMAT_EXTENSIONS.get(spec.name, spec.name)
        dest = self.store.output_path(
            config.category, config.slug, timestamp, extension=extension
        )
        return writer.write(rows, config.schema, dest)
