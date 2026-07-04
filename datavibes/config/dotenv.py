"""A tiny stdlib ``.env`` loader (no python-dotenv dependency).

Grammar: ``KEY=VALUE`` per line, ``#`` line comments, blank lines ignored, an
optional ``export`` prefix, and single/double quotes stripped around the value.
The whole remainder after ``=`` is the value (inline ``#`` is not treated as a
comment, so values may safely contain ``#``).

Precedence: real process environment variables ALWAYS win — ``load_dotenv``
never overwrites a variable that is already set (unless ``override=True``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import MutableMapping

_EXPORT_PREFIX = "export "


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse dotenv ``text`` into an ordered ``{KEY: VALUE}`` mapping."""
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(_EXPORT_PREFIX):
            line = line[len(_EXPORT_PREFIX):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        parsed[key] = _unquote(value.strip())
    return parsed


def load_dotenv(
    path: str | Path = ".env",
    *,
    override: bool = False,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Load ``path`` into ``environ`` (default ``os.environ``); return the pairs.

    A missing file is a silent no-op. Existing variables are preserved unless
    ``override`` is set — real env vars beat ``.env`` values.
    """
    target = os.environ if environ is None else environ
    dotenv_path = Path(path)
    if not dotenv_path.is_file():
        return {}
    pairs = parse_dotenv(dotenv_path.read_text(encoding="utf-8"))
    for key, value in pairs.items():
        if override or key not in target:
            target[key] = value
    return pairs


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
