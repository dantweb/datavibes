"""Config layer — AppConfig loading, defaults, interpolation, output-dir override."""

from datavibes.config.app_config import (
    OUTPUT_DIR_ENV_VAR,
    SECRET_ENV_VARS,
    describe_config,
    load_app_config,
)

FULL_YAML = """
paths:
  datasets_root: my-datasets
  output_root: my-output
  store_root: my-store
http:
  timeout_seconds: 12
  max_retries: 5
  backoff_seconds: 0.25
  user_agent: custom-agent
defaults:
  units: imperial
  format: json
"""

PARTIAL_YAML = """
http:
  timeout_seconds: 99
"""


def _write(tmp_path, body):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_full_file_maps_every_section(tmp_path):
    config = load_app_config(_write(tmp_path, FULL_YAML), environ={})
    assert config.paths.datasets_root == "my-datasets"
    assert config.paths.output_root == "my-output"
    assert config.http.timeout_seconds == 12
    assert config.http.max_retries == 5
    assert config.defaults.format == "json"


def test_partial_file_fills_gaps_with_defaults(tmp_path):
    config = load_app_config(_write(tmp_path, PARTIAL_YAML), environ={})
    assert config.http.timeout_seconds == 99  # from file
    assert config.http.max_retries == 3  # default
    assert config.paths.datasets_root == "datasets"  # default
    assert config.defaults.format == "csv"  # default


def test_absent_file_is_all_defaults(tmp_path):
    config = load_app_config(tmp_path / "missing.yaml", environ={})
    assert config.paths.datasets_root == "datasets"
    assert config.paths.output_root == "output"
    assert config.http.user_agent == "datavibes/0.1"
    assert config.defaults.units == "metric"


def test_env_interpolation_inside_config_values(tmp_path):
    body = 'http:\n  user_agent: "${MY_AGENT:-fallback-agent}"\n'
    absent = load_app_config(_write(tmp_path, body), environ={})
    assert absent.http.user_agent == "fallback-agent"
    present = load_app_config(_write(tmp_path, body), environ={"MY_AGENT": "live-agent"})
    assert present.http.user_agent == "live-agent"


def test_output_dir_env_overrides_config_absolute(tmp_path):
    override = tmp_path / "abs-out"
    config = load_app_config(
        _write(tmp_path, FULL_YAML),
        environ={OUTPUT_DIR_ENV_VAR: str(override)},
    )
    assert config.paths.output_root == str(override)


def test_output_dir_relative_resolved_against_project_root(tmp_path):
    config = load_app_config(
        tmp_path / "missing.yaml",
        environ={OUTPUT_DIR_ENV_VAR: "rel-out"},
        project_root=tmp_path,
    )
    assert config.paths.output_root == str((tmp_path / "rel-out").resolve())


def test_describe_masks_secret_values(tmp_path):
    config = load_app_config(tmp_path / "missing.yaml", environ={})
    rendered = describe_config(config, environ={"NCEI_TOKEN": "super-secret-123"})
    assert "super-secret-123" not in rendered
    assert "NCEI_TOKEN = ***set***" in rendered
    assert "OPENWEATHERMAP_API_KEY = ***unset***" in rendered
    for name in SECRET_ENV_VARS:
        assert name in rendered


def test_describe_shows_output_dir_unmasked(tmp_path):
    override = tmp_path / "abs-out"
    config = load_app_config(
        tmp_path / "missing.yaml",
        environ={OUTPUT_DIR_ENV_VAR: str(override)},
    )
    rendered = describe_config(config, environ={})
    assert str(override) in rendered  # a path, not a secret → shown in full
