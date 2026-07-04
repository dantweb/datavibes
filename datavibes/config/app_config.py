"""App-level (non-secret) configuration: ``config.yaml`` → typed ``AppConfig``.

Defaults apply when the file or a key is absent — the SDK works with no
``config.yaml`` present. Secrets never live here; they come from ``.env`` / the
process environment only.

Value precedence:
  * output root: ``DATAVIBES_OUTPUT_DIR`` env  >  ``config.yaml``  >  default
  * every other value: explicit caller arg  >  ``config.yaml``  >  default
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import os

import yaml

from datavibes.config.interpolate import interpolate_env

OUTPUT_DIR_ENV_VAR = "DATAVIBES_OUTPUT_DIR"

# Variables masked by ``datavibes config`` — never printed as a value.
SECRET_ENV_VARS = ("NCDC_WEB_SERVICE_TOKEN", "NCEI_TOKEN", "OPENWEATHERMAP_API_KEY")


@dataclass
class PathsConfig:
    datasets_root: str = "datasets"
    output_root: str = "output"
    store_root: str = "store"


@dataclass
class HttpConfig:
    timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_seconds: float = 0.5
    user_agent: str = "datavibes/0.1"


@dataclass
class DefaultsConfig:
    units: str = "metric"
    format: str = "csv"


@dataclass
class AppConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)


def load_app_config(
    path: str | Path = "config.yaml",
    *,
    environ: Mapping[str, str] | None = None,
    project_root: str | Path | None = None,
) -> AppConfig:
    """Build an :class:`AppConfig` from ``path`` (or all defaults if absent)."""
    source_env = os.environ if environ is None else environ
    config_path = Path(path)
    root = Path(project_root) if project_root is not None else Path.cwd()

    raw: dict = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{config_path} must contain a top-level mapping")
        raw = interpolate_env(loaded, source_env)  # type: ignore[assignment]

    paths = _build(PathsConfig, raw.get("paths"))
    http = _build(HttpConfig, raw.get("http"))
    defaults = _build(DefaultsConfig, raw.get("defaults"))

    paths.output_root = _resolve_output_root(paths.output_root, source_env, root)
    return AppConfig(paths=paths, http=http, defaults=defaults)


def describe_config(app_config: AppConfig, environ: Mapping[str, str]) -> str:
    """Render the effective config for ``datavibes config`` — secrets masked."""
    paths, http, defaults = app_config.paths, app_config.http, app_config.defaults
    lines = [
        "[paths]",
        f"datasets_root = {paths.datasets_root}",
        f"output_root = {paths.output_root}",
        f"store_root = {paths.store_root}",
        "[http]",
        f"timeout_seconds = {http.timeout_seconds}",
        f"max_retries = {http.max_retries}",
        f"backoff_seconds = {http.backoff_seconds}",
        f"user_agent = {http.user_agent}",
        "[defaults]",
        f"units = {defaults.units}",
        f"format = {defaults.format}",
        "[secrets]",
    ]
    for name in SECRET_ENV_VARS:
        lines.append(f"{name} = {'***set***' if environ.get(name) else '***unset***'}")
    return "\n".join(lines)


def _build(config_class, block):
    known = {item.name for item in dataclasses.fields(config_class)}
    values = {
        key: value for key, value in (block or {}).items() if key in known
    }
    return config_class(**values)


def _resolve_output_root(
    config_value: str, environ: Mapping[str, str], project_root: Path
) -> str:
    override = environ.get(OUTPUT_DIR_ENV_VAR)
    if not override:
        return config_value
    override_path = Path(override)
    if not override_path.is_absolute():
        override_path = (project_root / override_path).resolve()
    return str(override_path)
