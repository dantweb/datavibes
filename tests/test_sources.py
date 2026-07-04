"""S03 — built-in source adapters (network mocked, zero live calls)."""

import pytest

from datavibes.context import FetchContext
from datavibes.errors import SourceFetchError
from datavibes.sources.http_csv import HttpCsvSource
from datavibes.sources.http_json import HttpJsonSource
from datavibes.sources.static import StaticSource
from tests.conftest import FakeResponse


def _ctx(session=None):
    return FetchContext(config=None, clock=None, http=session)


def test_static_yields_configured_records():
    source = StaticSource(records=[{"city": "Berlin", "aqi": 42}])
    assert list(source.fetch(_ctx())) == [{"city": "Berlin", "aqi": 42}]


def test_http_json_selects_nested_array(make_session):
    body = {"items": [{"a": 1}, {"a": 2}]}
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = HttpJsonSource(url="https://x/api", select="$.items[*]")
    assert list(source.fetch(_ctx(session))) == [{"a": 1}, {"a": 2}]


def test_http_json_select_miss_is_empty(make_session):
    body = {"items": []}
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = HttpJsonSource(url="https://x/api", select="$.missing[*]")
    assert list(source.fetch(_ctx(session))) == []


def test_http_json_non_2xx_raises_with_status(make_session):
    session = make_session(
        lambda url, params, headers: FakeResponse(status_code=404, json_body={})
    )
    source = HttpJsonSource(url="https://x/api", select="$")
    with pytest.raises(SourceFetchError) as info:
        list(source.fetch(_ctx(session)))
    assert "404" in str(info.value)


def test_http_json_retries_transient_5xx_then_gives_up(monkeypatch, make_session):
    import datavibes.sources.http_client as client

    sleeps: list[float] = []
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))
    session = make_session(
        lambda url, params, headers: FakeResponse(status_code=503, json_body={})
    )
    source = HttpJsonSource(url="https://x/api", select="$")
    with pytest.raises(SourceFetchError):
        list(source.fetch(_ctx(session)))
    # DEFAULT_RETRIES attempts → (retries - 1) backoff sleeps.
    assert len(session.calls) == client.DEFAULT_RETRIES
    assert len(sleeps) == client.DEFAULT_RETRIES - 1


def test_http_csv_parses_quoted_and_custom_delimiter(make_session):
    csv_text = 'city;note\nBerlin;"a; b"\nParis;plain\n'
    session = make_session(
        lambda url, params, headers: FakeResponse(text=csv_text)
    )
    source = HttpCsvSource(url="https://x/data.csv", delimiter=";")
    rows = list(source.fetch(_ctx(session)))
    assert rows == [
        {"city": "Berlin", "note": "a; b"},
        {"city": "Paris", "note": "plain"},
    ]
