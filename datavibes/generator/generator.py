"""``Generator`` — orchestrates ``sources[] → raw snapshot``.

A source only fetches; the generator owns tagging, ordering, and writing. A
source that yields nothing or raises contributes nothing — the run still
produces a snapshot from the healthy sources (LSP: degrade, never crash).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from datavibes.config.app_config import HttpConfig
from datavibes.config.models import DatasetConfig
from datavibes.context import Clock, FetchContext
from datavibes.registry import resolve_source
from datavibes.store.filestore import FileStore

SOURCE_TAG_FIELD = "_source"


@dataclass
class RawSnapshot:
    """The result of a generate run."""

    slug: str
    timestamp: datetime
    path: Path
    row_count: int
    records: list[dict] = field(default_factory=list)
    failed_sources: list[str] = field(default_factory=list)


class Generator:
    """Collects records from every source and writes one raw snapshot."""

    def __init__(
        self,
        store: FileStore,
        clock: Clock,
        http_factory=None,
        http_settings: HttpConfig | None = None,
    ):
        self.store = store
        self.clock = clock
        self._http_factory = http_factory
        self.http_settings = http_settings or HttpConfig()

    def generate(self, config: DatasetConfig, http=None) -> RawSnapshot:
        timestamp = self.clock.now()
        session = http if http is not None else self._build_http()
        ctx = FetchContext(
            config=config,
            clock=self.clock,
            http=session,
            http_settings=self.http_settings,
        )

        records: list[dict] = []
        failed: list[str] = []
        for index, spec in enumerate(config.sources):
            tag = f"{spec.type}#{index}"
            try:
                source = resolve_source(spec)
                fetched = list(source.fetch(ctx))
            except Exception as error:  # degrade to empty contribution, never crash
                failed.append(f"{tag}: {error}")
                continue
            for record in fetched:
                tagged = dict(record)
                tagged.setdefault(SOURCE_TAG_FIELD, tag)
                records.append(tagged)

        path = self.store.write_raw(config.slug, timestamp, records)
        return RawSnapshot(
            slug=config.slug,
            timestamp=timestamp,
            path=path,
            row_count=len(records),
            records=records,
            failed_sources=failed,
        )

    def _build_http(self):
        if self._http_factory is not None:
            return self._http_factory()
        return None
