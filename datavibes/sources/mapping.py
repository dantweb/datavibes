"""Shared record-shaping helpers for the fan-out HTTP source adapters (DRY).

Three tiny pure functions the ``multi_http_json`` / ``columnar_http_json``
adapters both need: substitute an item's values into a URL/param template, read
a dotted path out of a nested JSON body, and copy the carried item keys onto an
output row. Keeping them here means neither adapter re-implements templating.
"""

from __future__ import annotations

from typing import Any

_MISSING = object()


def render_template(template: str, item: dict) -> str:
    """Substitute ``{key}`` placeholders in ``template`` from ``item``.

    A placeholder with no matching item key is left untouched rather than
    raising — a config typo degrades to a 404 naming the bad URL, which is a far
    clearer failure than a ``KeyError`` deep in the fetch loop.
    """
    rendered = template
    for key, value in item.items():
        rendered = rendered.replace("{" + str(key) + "}", str(value))
    return rendered


def render_params(params: dict, item: dict) -> dict:
    """Render every string value of ``params`` through :func:`render_template`."""
    return {
        key: render_template(value, item) if isinstance(value, str) else value
        for key, value in params.items()
    }


def read_path(body: Any, path: str) -> Any:
    """Read a dotted path (``owner.login``) out of nested mappings/lists.

    Returns ``None`` for any miss — a source degrades to a null cell, never an
    exception (LSP: a partial upstream response still yields rows).
    """
    current: Any = body
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else _MISSING
        else:
            return None
        if current is _MISSING:
            return None
    return current


def project(record: Any, fields: dict | None) -> dict:
    """Reshape one source record into ``{column: value}`` via dotted paths.

    With no ``fields`` mapping the record passes through unchanged — the source
    already speaks the schema's column names.
    """
    if not fields:
        return record if isinstance(record, dict) else {}
    return {column: read_path(record, path) for column, path in fields.items()}


def carried(item: dict, carry: list[str] | None) -> dict:
    """The item keys copied onto each output row (all of them when unset)."""
    if carry is None:
        return dict(item)
    return {key: item[key] for key in carry if key in item}
