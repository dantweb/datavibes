"""S02 — config models + loader (round-trip, invariants, discovery)."""

import pytest

from datavibes.config.loader import discover, load_config
from datavibes.config.models import (
    DatasetConfig,
    DatasetMetadata,
    SourceSpec,
    StepSpec,
)
from datavibes.errors import ConfigError
from datavibes.schema.field import Field, Schema

VALID_YAML = """
metadata:
  slug: demo-set
  title: Demo Set
  category: test
sources:
  - type: static
    records:
      - { city: Berlin, aqi: 42 }
schema:
  - { name: city, dtype: str }
  - { name: aqi, dtype: int }
processing:
  - normalize
  - dedupe: { keys: [city] }
  - validate
"""


def _write(tmp_path, name, body):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "dataset.yaml").write_text(body, encoding="utf-8")
    return directory


def test_metadata_requires_kebab_slug():
    with pytest.raises(ConfigError):
        DatasetMetadata(slug="Not Kebab", title="T", category="c")


def test_config_requires_at_least_one_source():
    with pytest.raises(ConfigError):
        DatasetConfig(
            metadata=DatasetMetadata(slug="a", title="A", category="c"),
            schema=Schema(fields=[Field(name="x")]),
            sources=[],
        )


def test_config_requires_non_empty_schema():
    with pytest.raises(ConfigError):
        DatasetConfig(
            metadata=DatasetMetadata(slug="a", title="A", category="c"),
            schema=Schema(fields=[]),
            sources=[SourceSpec(type="static")],
        )


def test_load_config_round_trips(tmp_path):
    directory = _write(tmp_path, "demo-set", VALID_YAML)
    config = load_config(directory)
    assert config.slug == "demo-set"
    assert config.category == "test"
    assert config.schema.column_names() == ["city", "aqi"]
    assert config.sources[0].type == "static"
    assert config.sources[0].options["records"] == [{"city": "Berlin", "aqi": 42}]
    assert [step.name for step in config.processing] == [
        "normalize",
        "dedupe",
        "validate",
    ]
    assert config.processing[1].options == {"keys": ["city"]}


def test_step_spec_string_and_mapping():
    assert StepSpec(name="normalize").options == {}


def test_load_config_malformed_yaml(tmp_path):
    directory = _write(tmp_path, "bad", "metadata: [unclosed\n")
    with pytest.raises(ConfigError):
        load_config(directory)


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope")


def test_discover_finds_datasets_and_ignores_others(tmp_path):
    _write(tmp_path, "demo-set", VALID_YAML)
    (tmp_path / "not-a-dataset").mkdir()
    (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
    assert discover(tmp_path) == ["demo-set"]


def test_env_interpolation(monkeypatch, tmp_path):
    monkeypatch.setenv("MY_KEY", "secret-value")
    body = VALID_YAML.replace(
        "records:\n      - { city: Berlin, aqi: 42 }",
        'url: "https://x/${MY_KEY}"',
    ).replace("type: static", "type: http_json")
    directory = _write(tmp_path, "demo-set", body)
    config = load_config(directory)
    assert config.sources[0].options["url"] == "https://x/secret-value"
