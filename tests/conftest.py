"""Shared fixtures — a fixed clock and an isolated store per test."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from datavibes.context import FixedClock
from datavibes.store.filestore import FileStore

FIXED_INSTANT = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(FIXED_INSTANT)


@pytest.fixture
def store(tmp_path) -> FileStore:
    return FileStore(tmp_path)


class FakeResponse:
    """A minimal stand-in for a requests Response (no network)."""

    def __init__(self, *, status_code=200, json_body=None, text="", content=None):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text
        if content is not None:
            self.content = content

    def json(self):
        if self._json_body is None:
            raise ValueError("no JSON body")
        return self._json_body


class RecordingSession:
    """A fake HTTP session that returns queued responses and records calls."""

    def __init__(self, responder):
        self._responder = responder
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        return self._responder(url, params, headers)

    def post(self, url, json=None, headers=None, timeout=None):
        """POST bodies reach the responder as ``params`` (BLS takes its query as JSON)."""
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self._responder(url, json, headers)


@pytest.fixture
def make_session():
    def factory(responder):
        return RecordingSession(responder)

    return factory
