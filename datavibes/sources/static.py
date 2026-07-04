"""``static`` source — inline/fixture records, no network.

Used by ``new`` scaffolding and by tests: a dataset that boots green before any
real API is wired.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from datavibes.context import FetchContext
from datavibes.errors import SourceFetchError
from datavibes.interfaces import Source
from datavibes.registry import register_source


@register_source("static")
class StaticSource(Source):
    """Yield records from an inline ``records`` list or a referenced file."""

    def __init__(
        self,
        records: list[dict] | None = None,
        records_file: str | None = None,
    ):
        self.records = records or []
        self.records_file = records_file

    def fetch(self, ctx: FetchContext) -> Iterable[dict]:
        if self.records_file:
            return self._load_file(self.records_file)
        return list(self.records)

    @staticmethod
    def _load_file(records_file: str) -> list[dict]:
        path = Path(records_file)
        if not path.is_file():
            raise SourceFetchError(f"static records_file not found: {records_file}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SourceFetchError(
                f"static records_file must contain a JSON array: {records_file}"
            )
        return payload
