"""``DatasetSDK`` — the importable facade wiring the whole pipeline.

The CLI is a thin shell over this facade: one behaviour, two front doors.
Collaborators (clock, store, http session factory) are injected — no hidden
singletons, no module-level network client.
"""

from __future__ import annotations

import sys
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
import datavibes.maps as _builtin_maps

_ = (_builtin_sources, _builtin_processing, _builtin_export, _builtin_maps)

CONFIG_FILENAME = "dataset.yaml"
DEFAULT_ENV_FILE = ".env"
DEFAULT_CONFIG_FILE = "config.yaml"


def _default_http_factory():
    import requests

    return requests.Session()


def _default_llm_factory(llm_config):
    # Imported lazily so the core SDK never hard-depends on the report extras.
    from datavibes.report.llm import default_llm_client

    return default_llm_client(llm_config)


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
        llm_factory: Callable[[object], object] | None = None,
    ):
        # Load .env FIRST (real env wins), then build the app config so that
        # ${VAR} interpolation — in config.yaml and dataset.yaml — sees secrets.
        load_dotenv(env_file)
        self.app_config = app_config or load_app_config(config_file)

        paths = self.app_config.paths
        self.root = Path(root) if root is not None else Path(paths.datasets_root)
        self.clock = clock or SystemClock()
        self.store = store or FileStore(
            output_root=paths.output_root,
            store_root=paths.store_root,
            output_layout=paths.output_layout,
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
        self.llm_factory = llm_factory or _default_llm_factory

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
        from datavibes.registry import resolve_writer

        for output in config.outputs:
            resolve_writer(output.name, output.options)
        return config

    def info(self, slug: str) -> DatasetInfo:
        return self._info_for(self._load(slug))

    def dataset(self, slug: str) -> DatasetHandle:
        return DatasetHandle(self, slug)

    def latest_rows(self, slug: str) -> list[dict]:
        config = self._load(slug)
        latest = self.store.latest_output(config.category, config.slug, extension="csv")
        if latest is None:
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
        """The cron target: generate → process → export, composed in-memory.

        With an explicit ``fmt`` exactly that format is written; otherwise every
        declared output is written and the first one's path is returned.

        When ``llm.enabled`` is set, the dataset's reports (analytics.md /
        statistics.md / report.pdf) are authored afterwards. Report failures are
        logged and swallowed — a report problem must never fail a data run.
        """
        return self._run(slug, fmt=fmt, http=http)[0]

    def run_outputs(self, slug: str, http=None) -> list[Path]:
        """Like :meth:`run`, returning every declared output (one shared timestamp)."""
        return self._run(slug, fmt=None, http=http)

    def _run(self, slug: str, fmt: str | None, http) -> list[Path]:
        config = self._load(slug)
        snapshot = self.generator.generate(config, http=http)
        # A source that fails degrades to zero rows by design (LSP), which makes a
        # rate-limited API look exactly like a green run with an empty CSV. Say so.
        for failure in snapshot.failed_sources:
            print(f"warning: source failed -> {failure}", file=sys.stderr)
        processed, provenance = self.processor.process_with_provenance(config, snapshot.records)
        if fmt is not None:
            paths = [self.exporter.export(config, processed, fmt=fmt, provenance=provenance)]
        else:
            paths = self.exporter.export_outputs(
                config, processed, default_format=self._format(None), provenance=provenance
            )
        if self.app_config.llm.enabled:
            try:
                self._write_reports(config, processed)
            except Exception as error:  # degrade: never fail the run over a report
                print(f"warning: report generation failed: {error}", file=sys.stderr)
        return paths

    def report(self, slug: str, llm=None):
        """Author the dataset's reports from its latest processed rows.

        Explicit command — generates regardless of ``llm.enabled``. Returns the
        :class:`~datavibes.report.reporter.ReportArtifacts` (three written paths).
        """
        config = self._load(slug)
        rows = self.process(slug)
        return self._write_reports(config, rows, llm=llm)

    def _write_reports(self, config: DatasetConfig, rows: list[dict], llm=None):
        from datavibes.report.reporter import Reporter

        client = llm if llm is not None else self.llm_factory(self.app_config.llm)
        output_dir = self.store.dataset_output_dir(config.category, config.slug)
        report_config = self.app_config.report
        reporter = Reporter(
            client,
            template=report_config.template,
            charts_enabled=report_config.charts,
        )
        return reporter.generate(config, rows, output_dir, self.clock.now())

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
        latest = self.store.latest_output(config.category, config.slug, extension="csv")
        row_count = 0
        if latest is not None:
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
