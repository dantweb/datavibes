"""``Exporter`` — places processed rows at the delivery-contract path."""

from __future__ import annotations

from pathlib import Path

from datavibes.config.models import DatasetConfig
from datavibes.context import Clock
from datavibes.registry import resolve_writer
from datavibes.store.filestore import FileStore

_FORMAT_EXTENSIONS = {"csv": "csv", "json": "json", "parquet": "parquet"}


class Exporter:
    """Resolves a writer and writes to the output-contract path."""

    def __init__(self, store: FileStore, clock: Clock):
        self.store = store
        self.clock = clock

    def export(
        self, config: DatasetConfig, rows: list[dict], fmt: str = "csv"
    ) -> Path:
        writer = resolve_writer(fmt)
        extension = _FORMAT_EXTENSIONS.get(fmt, fmt)
        dest = self.store.output_path(
            config.category, config.slug, self.clock.now(), extension=extension
        )
        return writer.write(rows, config.schema, dest)
