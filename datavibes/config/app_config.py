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
SECRET_ENV_VARS = (
    "NCDC_WEB_SERVICE_TOKEN",
    "NCEI_TOKEN",
    "OPENWEATHERMAP_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
)


@dataclass
class PathsConfig:
    datasets_root: str = "datasets"
    output_root: str = "output"
    store_root: str = "store"
    # Where a dataset's generated output (snapshots + analytics.md /
    # statistics.md / report.pdf) lands under ``output_root``:
    #   "slug"     -> output/<slug>/                     (default; keeps the
    #                 authored datasets/<slug>/ profile folder clean)
    #   "category" -> output/<category>/<slug>-<hash>/   (legacy dataset-plugin
    #                 delivery contract)
    output_layout: str = "slug"


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
class LlmConfig:
    """LLM settings for report generation (non-secret; the key comes from env).

    ``enabled`` gates automatic report generation inside ``run``; the explicit
    ``datavibes report`` command generates regardless. ``api_key_env`` names the
    environment variable holding the API key — its value is never stored here.

    ``provider`` selects the client:
      * ``anthropic`` — Claude models (``effort`` applies).
      * ``openai`` — any OpenAI-compatible Chat Completions endpoint. Set
        ``base_url`` to the provider's URL (e.g. ``https://api.deepseek.com``),
        ``model`` to their model id (e.g. ``deepseek-chat``), and
        ``api_key_env`` to the env var holding that provider's key.
    """

    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"
    base_url: str = ""
    max_tokens: int = 4000
    effort: str = "medium"
    api_key_env: str = "ANTHROPIC_API_KEY"


@dataclass
class ReportConfig:
    """Report rendering settings (non-secret).

    ``charts`` toggles rendering the dataset's declared charts into the PDF.
    ``template`` is the HTML template used for the PDF (rendered with WeasyPrint
    when available; falls back to a plain built-in layout otherwise).
    """

    charts: bool = True
    template: str = "datasets/var/pdf/templates/report.html"


@dataclass
class AppConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    report: ReportConfig = field(default_factory=ReportConfig)


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
    llm = _build(LlmConfig, raw.get("llm"))
    report = _build(ReportConfig, raw.get("report"))

    paths.output_root = _resolve_output_root(paths.output_root, source_env, root)
    return AppConfig(paths=paths, http=http, defaults=defaults, llm=llm, report=report)


def describe_config(app_config: AppConfig, environ: Mapping[str, str]) -> str:
    """Render the effective config for ``datavibes config`` — secrets masked."""
    paths, http, defaults = app_config.paths, app_config.http, app_config.defaults
    llm = app_config.llm
    lines = [
        "[paths]",
        f"datasets_root = {paths.datasets_root}",
        f"output_root = {paths.output_root}",
        f"store_root = {paths.store_root}",
        f"output_layout = {paths.output_layout}",
        "[http]",
        f"timeout_seconds = {http.timeout_seconds}",
        f"max_retries = {http.max_retries}",
        f"backoff_seconds = {http.backoff_seconds}",
        f"user_agent = {http.user_agent}",
        "[defaults]",
        f"units = {defaults.units}",
        f"format = {defaults.format}",
        "[llm]",
        f"enabled = {llm.enabled}",
        f"provider = {llm.provider}",
        f"model = {llm.model}",
        f"base_url = {llm.base_url or '(default)'}",
        f"max_tokens = {llm.max_tokens}",
        f"effort = {llm.effort}",
        f"api_key_env = {llm.api_key_env}",
        "[report]",
        f"charts = {app_config.report.charts}",
        f"template = {app_config.report.template}",
        "[secrets]",
    ]
    # Mask the built-in secrets plus whichever env var the LLM key is read from.
    for name in list(dict.fromkeys((*SECRET_ENV_VARS, llm.api_key_env))):
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
