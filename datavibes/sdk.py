"""``DatasetSDK`` — the importable facade wiring the whole pipeline.

The CLI is a thin shell over this facade: one behaviour, two front doors.
Collaborators (clock, store, http session factory) are injected — no hidden
singletons, no module-level network client.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from datavibes.config.app_config import AppConfig, load_app_config
from datavibes.config.dotenv import load_dotenv
from datavibes.config.loader import discover, load_config, load_custom_sources
from datavibes.config.models import DatasetConfig
from datavibes.context import Clock, SystemClock
from datavibes.errors import ConfigError
from datavibes.export.exporter import Exporter
from datavibes.generator.generator import Generator, RawSnapshot
from datavibes.processing.processor import Processor
from datavibes.registry import resolve_source
from datavibes.store.filestore import FileStore

# Import the built-in strategy packages so their decorators register (side effect).
import datavibes.sources as _builtin_sources
import datavibes.processing as _builtin_processing
import datavibes.export as _builtin_export

_ = (_builtin_sources, _builtin_processing, _builtin_export)

CONFIG_FILENAME = "dataset.yaml"
DEFAULT_ENV_FILE = ".env"
DEFAULT_CONFIG_FILE = "config.yaml"


def _default_http_factory():
    import requests

    return requests.Session()


@dataclass
class DatasetInfo:
    """A snapshot of what the SDK knows about a dataset."""

    slug: str
    title: str
    category: str
    latest_output: Path | None
    row_count: int


class DatasetHandle:
    """A per-dataset handle for in-process consumers (library use)."""

    def __init__(self, sdk: "DatasetSDK", slug: str):
        self._sdk = sdk
        self.slug = slug

    def latest(self) -> list[dict]:
        return self._sdk.latest_rows(self.slug)


class DatasetSDK:
    """Load config → sources → generator → processor → exporter."""

    def __init__(
        self,
        root: str | Path | None = None,
        clock: Clock | None = None,
        store: FileStore | None = None,
        http_factory: Callable[[], object] | None = None,
        app_config: AppConfig | None = None,
        env_file: str | Path = DEFAULT_ENV_FILE,
        config_file: str | Path = DEFAULT_CONFIG_FILE,
    ):
        # Load .env FIRST (real env wins), then build the app config so that
        # ${VAR} interpolation — in config.yaml and dataset.yaml — sees secrets.
        load_dotenv(env_file)
        self.app_config = app_config or load_app_config(config_file)

        paths = self.app_config.paths
        self.root = Path(root) if root is not None else Path(paths.datasets_root)
        self.clock = clock or SystemClock()
        self.store = store or FileStore(
            output_root=paths.output_root, store_root=paths.store_root
        )
        self.http_factory = http_factory or _default_http_factory
        self.generator = Generator(
            self.store,
            self.clock,
            http_factory=self.http_factory,
            http_settings=self.app_config.http,
        )
        self.processor = Processor(self.clock)
        self.exporter = Exporter(self.store, self.clock)

    # ------------------------------------------------------------------ read
    def list(self) -> list[DatasetInfo]:
        infos: list[DatasetInfo] = []
        for slug in discover(self.root):
            config = self._load(slug)
            infos.append(self._info_for(config))
        return infos

    def validate(self, slug: str) -> DatasetConfig:
        """Load config and confirm every source + step resolves."""
        config = self._load(slug)
        for spec in config.sources:
            resolve_source(spec)
        from datavibes.registry import resolve_step

        for spec in config.processing:
            resolve_step(spec)
        return config

    def info(self, slug: str) -> DatasetInfo:
        return self._info_for(self._load(slug))

    def dataset(self, slug: str) -> DatasetHandle:
        return DatasetHandle(self, slug)

    def latest_rows(self, slug: str) -> list[dict]:
        config = self._load(slug)
        latest = self.store.latest_output(config.category, config.slug)
        if latest is None or latest.suffix != ".csv":
            return []
        return _read_csv(latest)

    # --------------------------------------------------------------- pipeline
    def generate(self, slug: str, http=None) -> RawSnapshot:
        config = self._load(slug)
        return self.generator.generate(config, http=http)

    def process(self, slug: str) -> list[dict]:
        config = self._load(slug)
        raw_rows = self.store.read_latest_raw(config.slug)
        return self.processor.process(config, raw_rows)

    def export(self, slug: str, fmt: str | None = None) -> Path:
        config = self._load(slug)
        rows = self.process(slug)
        return self.exporter.export(config, rows, fmt=self._format(fmt))

    def run(self, slug: str, fmt: str | None = None, http=None) -> Path:
        """The cron target: generate → process → export, composed in-memory."""
        config = self._load(slug)
        snapshot = self.generator.generate(config, http=http)
        processed = self.processor.process(config, snapshot.records)
        return self.exporter.export(config, processed, fmt=self._format(fmt))

    def _format(self, fmt: str | None) -> str:
        # Precedence: explicit arg > config.yaml defaults.format > built-in.
        return fmt if fmt is not None else self.app_config.defaults.format

    # ---------------------------------------------------------------- scaffold
    def scaffold(self, slug: str, category: str) -> Path:
        """Write a ``static``-source ``dataset.yaml`` that passes ``validate``."""
        dataset_dir = self.root / slug
        config_path = dataset_dir / CONFIG_FILENAME
        if config_path.exists():
            raise ConfigError(f"dataset '{slug}' already exists at {config_path}")
        dataset_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_scaffold_yaml(slug, category), encoding="utf-8")
        return config_path

    # ---------------------------------------------------------------- helpers
    def _load(self, slug: str) -> DatasetConfig:
        dataset_dir = self.root / slug
        config_path = dataset_dir / CONFIG_FILENAME
        if not config_path.is_file():
            raise ConfigError(f"unknown dataset '{slug}' (looked in {dataset_dir})")
        load_custom_sources(dataset_dir)
        return load_config(config_path)

    def _info_for(self, config: DatasetConfig) -> DatasetInfo:
        latest = self.store.latest_output(config.category, config.slug)
        row_count = 0
        if latest is not None and latest.suffix == ".csv":
            row_count = max(0, len(_read_csv(latest)))
        return DatasetInfo(
            slug=config.slug,
            title=config.metadata.title,
            category=config.category,
            latest_output=latest,
            row_count=row_count,
        )


def _read_csv(path: Path) -> list[dict]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _scaffold_yaml(slug: str, category: str) -> str:
    return f"""metadata:
  slug: {slug}
  title: {slug.replace('-', ' ').title()}
  category: {category}
  license: ""
  update_frequency: daily
  attribution: ""

schema:
  - {{ name: city,  dtype: str }}
  - {{ name: value, dtype: int }}

sources:
  - type: static
    records:
      - {{ city: Demo, value: 1 }}

processing:
  - normalize
  - validate
"""
