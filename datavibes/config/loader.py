"""Load + discover dataset configs from the ``datasets/`` tree.

The loader parses ``dataset.yaml`` into a :class:`DatasetConfig`. It does *not*
instantiate sources or steps — that needs the registries and happens lazily at
run time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

from datavibes.config.interpolate import interpolate_env
from datavibes.config.models import (
    ChartSpec,
    DatasetConfig,
    DatasetMetadata,
    OutputSpec,
    SourceSpec,
    StepSpec,
)
from datavibes.errors import ConfigError
from datavibes.schema.field import Field, Schema

CONFIG_FILENAME = "dataset.yaml"
CUSTOM_SOURCES_FILENAME = "sources.py"


def load_config(path: str | Path) -> DatasetConfig:
    """Parse a ``dataset.yaml`` at ``path`` (file or its directory)."""
    config_path = _resolve_config_path(Path(path))
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed YAML in {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a top-level mapping")

    metadata = _parse_metadata(raw.get("metadata"), config_path)
    schema = _parse_schema(raw.get("schema"), config_path)
    sources = _parse_sources(raw.get("sources"), config_path)
    processing = _parse_processing(raw.get("processing") or [], config_path)
    charts = _parse_charts(raw.get("charts") or [], config_path)
    outputs = _parse_outputs(raw.get("outputs") or [], config_path)
    return DatasetConfig(
        metadata=metadata,
        schema=schema,
        sources=sources,
        processing=processing,
        charts=charts,
        outputs=outputs,
    )


def discover(root: str | Path) -> list[str]:
    """List dataset slugs under ``root`` (dirs containing a ``dataset.yaml``)."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    slugs = [
        child.name
        for child in sorted(root_path.iterdir())
        if child.is_dir() and (child / CONFIG_FILENAME).is_file()
    ]
    return slugs


def load_custom_sources(dataset_dir: str | Path) -> None:
    """Import a dataset's optional ``sources.py`` so its adapters register."""
    module_path = Path(dataset_dir) / CUSTOM_SOURCES_FILENAME
    if not module_path.is_file():
        return
    module_name = f"datavibes_dataset_sources_{Path(dataset_dir).name}"
    if module_name in sys.modules:
        # Already imported this session — re-exec would re-register and collide.
        return
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot import custom sources from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def _resolve_config_path(path: Path) -> Path:
    config_path = path / CONFIG_FILENAME if path.is_dir() else path
    if not config_path.is_file():
        raise ConfigError(f"no {CONFIG_FILENAME} found at {path}")
    return config_path


def _parse_metadata(block: object, config_path: Path) -> DatasetMetadata:
    if not isinstance(block, dict):
        raise ConfigError(f"{config_path}: 'metadata' must be a mapping")
    known = {
        "slug",
        "title",
        "category",
        "license",
        "update_frequency",
        "attribution",
    }
    filtered = {key: value for key, value in block.items() if key in known}
    try:
        return DatasetMetadata(**filtered)
    except TypeError as exc:
        raise ConfigError(f"{config_path}: invalid metadata ({exc})") from exc


def _parse_schema(block: object, config_path: Path) -> Schema:
    if not isinstance(block, list) or not block:
        raise ConfigError(f"{config_path}: 'schema' must be a non-empty list")
    fields: list[Field] = []
    for entry in block:
        if not isinstance(entry, dict):
            raise ConfigError(f"{config_path}: each schema entry must be a mapping")
        fields.append(Field(**entry))
    return Schema(fields=fields)


def _parse_sources(block: object, config_path: Path) -> list[SourceSpec]:
    if not isinstance(block, list) or not block:
        raise ConfigError(f"{config_path}: 'sources' must be a non-empty list")
    specs: list[SourceSpec] = []
    for entry in block:
        if not isinstance(entry, dict) or "type" not in entry:
            raise ConfigError(
                f"{config_path}: each source must be a mapping with a 'type'"
            )
        source_type = entry["type"]
        options = {
            key: interpolate_env(value)
            for key, value in entry.items()
            if key != "type"
        }
        specs.append(SourceSpec(type=source_type, options=options))
    return specs


def _parse_processing(block: object, config_path: Path) -> list[StepSpec]:
    if not isinstance(block, list):
        raise ConfigError(f"{config_path}: 'processing' must be a list")
    specs: list[StepSpec] = []
    for entry in block:
        specs.append(_parse_step(entry, config_path))
    return specs


def _parse_charts(block: object, config_path: Path) -> list[ChartSpec]:
    if not isinstance(block, list):
        raise ConfigError(f"{config_path}: 'charts' must be a list")
    known = {"type", "title", "x", "y", "series", "agg", "filter", "sort", "limit"}
    specs: list[ChartSpec] = []
    for entry in block:
        if not isinstance(entry, dict):
            raise ConfigError(f"{config_path}: each chart must be a mapping")
        filtered = {key: value for key, value in entry.items() if key in known}
        try:
            specs.append(ChartSpec(**filtered))
        except TypeError as exc:
            raise ConfigError(f"{config_path}: invalid chart ({exc})") from exc
    return specs


def _parse_outputs(block: object, config_path: Path) -> list[OutputSpec]:
    """``outputs:`` entries share the step syntax: a name or ``{name: {options}}``."""
    if not isinstance(block, list):
        raise ConfigError(f"{config_path}: 'outputs' must be a list")
    return [
        OutputSpec(name=step.name, options=step.options)
        for step in (_parse_step(entry, config_path, kind="output") for entry in block)
    ]


def _parse_step(entry: object, config_path: Path, kind: str = "processing step") -> StepSpec:
    if isinstance(entry, str):
        return StepSpec(name=entry, options={})
    if isinstance(entry, dict) and len(entry) == 1:
        name, options = next(iter(entry.items()))
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ConfigError(
                f"{config_path}: options for {kind} '{name}' must be a mapping"
            )
        return StepSpec(name=name, options=interpolate_env(options))
    raise ConfigError(
        f"{config_path}: a {kind} must be a name or a single-key mapping"
    )
