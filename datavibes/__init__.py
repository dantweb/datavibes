"""datavibes — a config-driven toolkit for collecting data and generating datasets.

Public API surface (also everything the CLI does is reachable here):

    from datavibes import DatasetSDK, Source, Field, register_source
"""

from __future__ import annotations

from datavibes.config.app_config import AppConfig, describe_config, load_app_config
from datavibes.config.dotenv import load_dotenv
from datavibes.context import (
    Clock,
    FetchContext,
    FixedClock,
    RunContext,
    SystemClock,
)
from datavibes.errors import (
    ConfigError,
    DatavibesError,
    SchemaValidationError,
    SourceFetchError,
    UnknownStrategyError,
)
from datavibes.interfaces import ProcessingStep, Source, Writer
from datavibes.registry import (
    register_source,
    register_step,
    register_writer,
    resolve_source,
    resolve_step,
    resolve_writer,
)
from datavibes.schema.field import Field, Schema
from datavibes.sdk import DatasetSDK

# Importing these packages registers the built-in strategies (side effect).
import datavibes.sources as _builtin_sources
import datavibes.processing as _builtin_processing
import datavibes.export as _builtin_export

_ = (_builtin_sources, _builtin_processing, _builtin_export)

__all__ = [
    "DatasetSDK",
    "Source",
    "ProcessingStep",
    "Writer",
    "Field",
    "Schema",
    "register_source",
    "register_step",
    "register_writer",
    "resolve_source",
    "resolve_step",
    "resolve_writer",
    "Clock",
    "FixedClock",
    "SystemClock",
    "FetchContext",
    "RunContext",
    "AppConfig",
    "load_app_config",
    "describe_config",
    "load_dotenv",
    "DatavibesError",
    "ConfigError",
    "SchemaValidationError",
    "SourceFetchError",
    "UnknownStrategyError",
]

__version__ = "0.1.0"
