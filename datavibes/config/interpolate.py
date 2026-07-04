"""``${VAR}`` environment interpolation shared by the config + dataset loaders.

Supports ``${VAR}`` (empty string when unset) and ``${VAR:-default}`` (the
default applies when the variable is unset or empty). Resolution reads
``os.environ``; secrets loaded from ``.env`` are already merged there by the
dotenv loader, and real process env vars always win.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def interpolate_env(value: object, environ: Mapping[str, str] | None = None) -> object:
    """Recursively substitute ``${VAR}`` / ``${VAR:-default}`` in ``value``."""
    source = os.environ if environ is None else environ

    def replace(match: "re.Match[str]") -> str:
        name, default = match.group(1), match.group(2)
        resolved = source.get(name, "")
        if resolved:
            return resolved
        return default if default is not None else ""

    if isinstance(value, str):
        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [interpolate_env(item, source) for item in value]
    if isinstance(value, dict):
        return {key: interpolate_env(item, source) for key, item in value.items()}
    return value
