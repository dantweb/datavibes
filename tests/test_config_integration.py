"""Config layer — end-to-end wiring into the SDK, FileStore, http, and CLI."""

import os
from datetime import datetime, timezone

import pytest

from datavibes import DatasetSDK
from datavibes.cli import main
from datavibes.config.app_config import HttpConfig
from datavibes.config.models import (
    DatasetConfig,
    DatasetMetadata,
    SourceSpec,
)
from datavibes.context import FetchContext, FixedClock
from datavibes.generator.generator import Generator
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.schema.field import Field, Schema
from datavibes.sources.http_json import HttpJsonSource
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse

FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))

HTTP_DATASET_YAML = """
metadata:
  slug: token-ds
  title: Token DS
  category: test
sources:
  - type: http_json
    url: "https://api.example.com/data?token=${DV_TEST_TOKEN}"
    select: "$"
schema:
  - { name: value, dtype: int }
processing:
  - validate
"""


@pytest.fixture(autouse=True)
def _isolate_environ():
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@register_source("test-capture-settings")
class _CaptureSettingsSource(Source):
    captured = {}

    def fetch(self, ctx):
        _CaptureSettingsSource.captured["timeout"] = ctx.http_settings.timeout_seconds
        return []


def _missing(tmp_path):
    return tmp_path / "no-such.yaml"


def test_dotenv_var_flows_into_dataset_yaml_interpolation(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DV_TEST_TOKEN=secret-tok\n", encoding="utf-8")
    datasets = tmp_path / "datasets"
    dataset_dir = datasets / "token-ds"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "dataset.yaml").write_text(HTTP_DATASET_YAML, encoding="utf-8")

    sdk = DatasetSDK(
        root=datasets,
        clock=FIXED,
        store=FileStore(tmp_path),
        env_file=env_file,
        config_file=_missing(tmp_path),
    )
    config = sdk.validate("token-ds")
    assert config.sources[0].options["url"].endswith("token=secret-tok")


def test_http_settings_flow_into_source(make_session):
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=[{"value": 1}])
    )
    settings = HttpConfig(timeout_seconds=7, max_retries=1, user_agent="UA/9")
    ctx = FetchContext(config=None, clock=FIXED, http=session, http_settings=settings)
    list(HttpJsonSource(url="https://x/api", select="$[*]").fetch(ctx))
    assert session.calls[0]["timeout"] == 7
    assert session.calls[0]["headers"]["User-Agent"] == "UA/9"


def test_generator_injects_http_settings(store):
    config = DatasetConfig(
        metadata=DatasetMetadata(slug="cap", title="Cap", category="test"),
        schema=Schema([Field(name="a", dtype="int")]),
        sources=[SourceSpec(type="test-capture-settings")],
    )
    Generator(store, FIXED, http_settings=HttpConfig(timeout_seconds=42)).generate(config)
    assert _CaptureSettingsSource.captured["timeout"] == 42


def test_output_dir_env_lands_snapshot_under_configured_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "custom-output"
    os.environ["DATAVIBES_OUTPUT_DIR"] = str(output_dir)
    (tmp_path / "datasets").mkdir()

    sdk = DatasetSDK(clock=FIXED, env_file=_missing(tmp_path), config_file=_missing(tmp_path))
    sdk.scaffold("demo", "test")
    path = sdk.run("demo")
    assert str(output_dir) in str(path)
    assert path.exists()


def test_no_output_dir_env_uses_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.environ.pop("DATAVIBES_OUTPUT_DIR", None)
    sdk = DatasetSDK(clock=FIXED, env_file=_missing(tmp_path), config_file=_missing(tmp_path))
    assert sdk.app_config.paths.output_root == "output"


def test_sdk_runs_with_neither_file_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasets").mkdir()
    sdk = DatasetSDK(clock=FIXED)  # .env + config.yaml both absent in tmp cwd
    assert sdk.app_config.paths.datasets_root == "datasets"
    assert sdk.app_config.http.max_retries == 3
    sdk.scaffold("demo", "test")
    path = sdk.run("demo")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "city,value\nDemo,1\n"


def test_cli_config_masks_secret_value(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    os.environ["NCEI_TOKEN"] = "tok-should-never-print"
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "tok-should-never-print" not in out
    assert "NCEI_TOKEN = ***set***" in out


def test_cli_config_shows_output_dir_unmasked(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "abs-out"
    os.environ["DATAVIBES_OUTPUT_DIR"] = str(output_dir)
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert str(output_dir) in out
