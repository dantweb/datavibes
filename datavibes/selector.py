"""A tiny, dependency-free JSONPath-lite selector.

Supports exactly the shapes the built-in HTTP sources need — no more (no
overengineering, no external jsonpath dependency):

- ``$``            → the whole body
- ``$.a``          → ``body["a"]``
- ``$.a.b``        → nested mapping access
- ``$.a[*]``       → the list at ``body["a"]`` (each element)
- ``$[*]``         → the body itself, which must be a list

A selection that resolves to a single mapping yields one record; a selection
that resolves to a list yields each element. A miss yields no records (empty),
never an exception — a source degrades to an empty snapshot (LSP).
"""

from __future__ import annotations

import re
from typing import Any, Iterator

_TOKEN = re.compile(r"\.([A-Za-z0-9_\-]+)|\[\*\]")

_MISSING = object()


def select(body: Any, expression: str) -> Iterator[dict]:
    """Yield ``dict`` records selected from ``body`` by ``expression``."""
    expression = (expression or "$").strip()
    if not expression.startswith("$"):
        raise ValueError(f"selector must start with '$': {expression!r}")

    current: list[Any] = [body]
    for key, is_wildcard in _tokens(expression):
        nxt: list[Any] = []
        for node in current:
            if is_wildcard:
                if isinstance(node, list):
                    nxt.extend(node)
            elif isinstance(node, dict):
                value = node.get(key, _MISSING)
                if value is not _MISSING:
                    nxt.append(value)
        current = nxt

    for node in current:
        if isinstance(node, dict):
            yield node
        elif isinstance(node, list):
            for element in node:
                if isinstance(element, dict):
                    yield element


def _tokens(expression: str) -> Iterator[tuple[str, bool]]:
    remainder = expression[1:]
    position = 0
    for match in _TOKEN.finditer(remainder):
        if match.start() != position:
            raise ValueError(f"unsupported selector syntax: {expression!r}")
        position = match.end()
        if match.group(0) == "[*]":
            yield "", True
        else:
            yield match.group(1), False
    if position != len(remainder):
        raise ValueError(f"unsupported selector syntax: {expression!r}")
