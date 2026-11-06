"""``FileStore`` — the only component that touches the filesystem.

It owns two trees, both rooted under an injectable base:

* **raw store** — ``<base>/<store_root>/raw/<slug>/<ts>.jsonl`` — the immutable
  per-run snapshot the generator writes and the processor reads.
* **output** — ``<base>/<output_root>/<category>/<slug>-<hash>/<ts>.csv`` — the
  delivery-contract path the ``dataset`` plugin serves unchanged.

Writes are **byte-stable**: given the same records and instant, the bytes on
disk are identical (sorted JSON keys, fixed line terminator, injected clock).
Nothing here reads the wall clock — the instant is always passed in.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from datavibes.context import format_timestamp

RAW_SUFFIX = ".jsonl"
_HASH_LENGTH = 8

# A snapshot filename is a ``YYYY-MM-DD-HH-MM`` timestamp plus an extension.
# Report artifacts (analytics.md / statistics.md / report.pdf) sit in the same
# output folder under the "slug" layout, so "latest snapshot" queries must match
# only timestamp-named files.
_SNAPSHOT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}\.")


def slug_hash(slug: str) -> str:
    """A short, stable directory suffix disambiguating same-named slugs."""
    return hashlib.sha1(slug.encode("utf-8")).hexdigest()[:_HASH_LENGTH]


class FileStore:
    """Path builders + byte-stable read/write for raw snapshots and outputs."""

    def __init__(
        self,
        base: str | Path | None = None,
        output_root: str | Path = "output",
        store_root: str | Path = "store",
        output_layout: str = "slug",
    ):
        self.base = Path(base) if base is not None else Path(".")
        self.output_root = str(output_root)
        self.store_root = str(store_root)
        self.output_layout = output_layout

    # ------------------------------------------------------------ path builders
    def dataset_output_dir(self, category: str, slug: str) -> Path:
        """The folder holding a dataset's generated output (snapshots + reports).

        ``slug`` layout keeps it separate from the authored ``datasets/<slug>/``
        profile; ``category`` layout reproduces the legacy plugin contract.
        """
        root = self.base / self.output_root
        if self.output_layout == "category":
            return root / category / f"{slug}-{slug_hash(slug)}"
        return root / slug

    def output_path(
        self,
        category: str,
        slug: str,
        instant: datetime,
        extension: str = "csv",
    ) -> Path:
        """The output path for one snapshot, under the dataset's output dir."""
        filename = f"{format_timestamp(instant)}.{extension}"
        return self.dataset_output_dir(category, slug) / filename

    def raw_path(self, slug: str, instant: datetime) -> Path:
        """The raw-snapshot path for one generate run."""
        filename = f"{format_timestamp(instant)}{RAW_SUFFIX}"
        return self.base / self.store_root / "raw" / slug / filename

    # -------------------------------------------------------------------- raw io
    def write_raw(self, slug: str, instant: datetime, records: list[dict]) -> Path:
        """Write ``records`` as byte-stable JSONL; return the written path."""
        path = self.raw_path(slug, instant)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(record, sort_keys=True, ensure_ascii=False)
            for record in records
        ]
        body = "\n".join(lines)
        if body:
            body += "\n"
        path.write_text(body, encoding="utf-8")
        return path

    def read_raw(self, path: str | Path) -> list[dict]:
        """Read a JSONL raw snapshot back into a list of dicts."""
        text = Path(path).read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def read_latest_raw(self, slug: str) -> list[dict]:
        """Read the most recent raw snapshot for ``slug`` (empty if none)."""
        raw_dir = self.base / self.store_root / "raw" / slug
        latest = _latest_snapshot(raw_dir)
        return self.read_raw(latest) if latest is not None else []

    # ----------------------------------------------------------------- output io
    def latest_output(
        self, category: str, slug: str, extension: str | None = None
    ) -> Path | None:
        """The most recent snapshot for ``category``/``slug`` (or ``None``).

        Only timestamp-named files count — report artifacts sharing the folder
        are ignored. ``extension`` (e.g. ``"csv"``) narrows it to one format, for
        datasets that write several outputs per run (csv + svg map + join report).
        """
        return _latest_snapshot(self.dataset_output_dir(category, slug), extension)


def _latest_snapshot(folder: str | Path, extension: str | None = None) -> Path | None:
    directory = Path(folder)
    if not directory.is_dir():
        return None
    suffix = f".{extension}" if extension else ""
    files = sorted(
        child
        for child in directory.iterdir()
        if child.is_file()
        and _SNAPSHOT_NAME.match(child.name)
        and child.name.endswith(suffix)
    )
    return files[-1] if files else None
