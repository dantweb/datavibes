"""S13 — the ``svg-map`` writer, the ``outputs:`` list, and multi-output runs."""

import json
import os
import re
import textwrap
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.config.loader import load_config
from datavibes.errors import ConfigError, UnknownStrategyError
from datavibes.export.exporter import Exporter
from datavibes.registry import resolve_writer
from datavibes.schema.field import Field, Schema

FIXTURES = Path(__file__).parent / "fixtures" / "geometry"
MANIFEST = str(FIXTURES / "manifest.yaml")
GOLDEN = Path(__file__).parent / "golden"

SCHEMA = Schema([Field(name="code"), Field(name="name"), Field(name="density", dtype="float"),
                 Field(name="male", dtype="float")])
ROWS = [
    {"code": "AAA", "name": "Alpha", "density": 1.0, "male": 52.0},
    {"code": "BBB", "name": "Beta", "density": 10.0, "male": 48.0},
    {"code": "XCC", "name": "Gamma", "density": 100.0, "male": 47.0},  # aliased to CCC
    {"code": "ZZZ", "name": "Nowhere", "density": 5.0, "male": 50.0},  # no geometry
]


def _writer(**overrides):
    options = {
        "geometry": "fixture-countries",
        "geometry_manifest": MANIFEST,
        "key_column": "code",
        "key_aliases": {"XCC": "CCC"},
        "label_columns": ["name", "density"],
        "title": "Fixture map",
        "footer": "Source: fixture",
        "color_scale": {"type": "sex-ratio-bivariate", "ratio_column": "male",
                        "value_column": "density", "value_label": "people/km²"},
    }
    options.update(overrides)
    return resolve_writer("svg-map", options)


def _assert_golden(path: Path, name: str):
    golden = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(path.read_bytes())
    assert path.read_bytes() == golden.read_bytes(), f"{name} drifted (UPDATE_GOLDEN=1 to accept)"


def _fill_of(svg: str, key: str) -> str:
    match = re.search(rf'<path id="{key}" fill="(#[0-9a-f]{{6}})"', svg)
    assert match, f"no path for {key}"
    return match.group(1)


# ---------------------------------------------------------------- the writer
def test_svg_matches_golden_and_is_byte_stable(tmp_path):
    first = _writer().write(ROWS, SCHEMA, tmp_path / "a" / "2026-06-01-00-00.svg")
    second = _writer().write(ROWS, SCHEMA, tmp_path / "b" / "2026-06-01-00-00.svg")
    assert first.read_bytes() == second.read_bytes()
    _assert_golden(first, "fixture_bivariate.svg")


def test_svg_fills_follow_the_scale_and_no_data_is_grey(tmp_path):
    svg = _writer().write(ROWS, SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8")
    assert _fill_of(svg, "AAA") != _fill_of(svg, "BBB")
    assert _fill_of(svg, "DDD") == "#d9d9d9"  # feature without a data row
    assert 'fill-rule="evenodd"' in svg      # the hole in CCC
    assert svg.index('id="AAA"') < svg.index('id="BBB"') < svg.index('id="CCC"')


def test_svg_escapes_text_and_carries_title_legend_footer(tmp_path):
    svg = _writer().write(ROWS, SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8")
    assert "Gamma &amp; &lt;Co&gt;" in svg
    assert "Fixture map" in svg and "Source: fixture" in svg and "Fixture geometry" in svg
    assert "More men than women" in svg and "No data" in svg
    assert "<title>" in svg and "density: 100" in svg
    assert "2026" not in svg  # no generation timestamp leaks into the drawing


def test_join_report_lists_both_directions(tmp_path):
    dest = _writer().write(ROWS, SCHEMA, tmp_path / "2026-06-01-00-00.svg")
    report = json.loads((tmp_path / "2026-06-01-00-00.join.json").read_text(encoding="utf-8"))
    assert dest.name == "2026-06-01-00-00.svg"
    assert report["features_without_rows"] == ["DDD"]
    assert report["rows_not_drawn"] == ["ZZZ"]
    assert report["drawn_features"] == 4 and report["matched_features"] == 3


def test_empty_rows_render_an_all_no_data_map(tmp_path):
    svg = _writer().write([], SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8")
    assert all(_fill_of(svg, key) == "#d9d9d9" for key in ("AAA", "BBB", "CCC", "DDD"))


def test_spectral_scale_swaps_in_without_writer_changes(tmp_path):
    writer = _writer(color_scale={"type": "spectral-density", "value_column": "density"})
    svg = writer.write(ROWS, SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8")
    assert _fill_of(svg, "AAA") == "#08306b"  # lowest among all rows
    assert _fill_of(svg, "CCC") == "#d7191c"  # highest
    _assert_golden(tmp_path / "m.svg", "fixture_spectral.svg")


def test_region_scope_and_clip_bbox_change_the_viewbox(tmp_path):
    world = _writer().write(ROWS, SCHEMA, tmp_path / "w.svg").read_text(encoding="utf-8")
    europe = _writer(scope="region", region={"continent": "Europe"}).write(
        ROWS, SCHEMA, tmp_path / "e.svg").read_text(encoding="utf-8")
    assert 'id="CCC"' not in europe and 'id="AAA"' in europe
    clipped = _writer(scope="region", region={"continent": "Europe"},
                      clip_bbox=[0, 40, 10, 50]).write(ROWS, SCHEMA, tmp_path / "c.svg").read_text(encoding="utf-8")
    viewboxes = {re.search(r'viewBox="([^"]+)"', svg).group(1) for svg in (world, europe, clipped)}
    assert len(viewboxes) == 3


def test_country_scope_on_admin1_fixture(tmp_path):
    rows = [{"code": "AAA-1", "density": 3.0, "male": 51.0}, {"code": "AAA-2", "density": 30.0, "male": 49.0}]
    svg = _writer(geometry="fixture-admin1", scope="country", country="AAA", key_aliases={}).write(
        rows, SCHEMA, tmp_path / "c.svg").read_text(encoding="utf-8")
    assert 'id="AAA-1"' in svg and 'id="AAA-2"' in svg and 'id="BBB-1"' not in svg


def test_bad_options_fail_at_construction():
    with pytest.raises(UnknownStrategyError):
        _writer(color_scale={"type": "nope"})
    with pytest.raises(ConfigError):
        _writer(geometry="atlantis")
    with pytest.raises(ConfigError):
        _writer(scope="galaxy")
    with pytest.raises(ConfigError):
        _writer(projection="mercator")


# -------------------------------------------------- outputs list + exporter
def _write_dataset(root: Path, outputs_block: str) -> Path:
    dataset_dir = root / "mapdemo"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "dataset.yaml").write_text(textwrap.dedent(f"""
        metadata: {{ slug: mapdemo, title: Map Demo, category: colored-geostats }}
        schema:
          - {{ name: code, dtype: str }}
          - {{ name: name, dtype: str }}
          - {{ name: density, dtype: float }}
          - {{ name: male, dtype: float }}
        sources:
          - type: static
            records:
              - {{ code: AAA, name: Alpha, density: 1.0, male: 52.0 }}
              - {{ code: BBB, name: Beta, density: 10.0, male: 48.0 }}
        processing: [normalize, validate]
    """) + outputs_block, encoding="utf-8")
    return dataset_dir


OUTPUTS_BLOCK = textwrap.dedent(f"""
    outputs:
      - csv
      - svg-map:
          geometry: fixture-countries
          geometry_manifest: {MANIFEST}
          key_column: code
          color_scale: {{ type: spectral-density, value_column: density }}
""")


def test_outputs_are_parsed_as_writer_specs(tmp_path):
    config = load_config(_write_dataset(tmp_path, OUTPUTS_BLOCK))
    assert [spec.name for spec in config.outputs] == ["csv", "svg-map"]
    assert config.outputs[1].options["key_column"] == "code"


def test_duplicate_outputs_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write_dataset(tmp_path, "outputs: [csv, csv]\n"))


def test_run_outputs_share_one_timestamp_stem(tmp_path, fixed_clock, store):
    _write_dataset(tmp_path / "datasets", OUTPUTS_BLOCK)
    sdk = DatasetSDK(root=tmp_path / "datasets", clock=fixed_clock, store=store,
                     env_file=tmp_path / "none.env", config_file=tmp_path / "none.yaml")
    paths = sdk.run_outputs("mapdemo")
    assert [path.name for path in paths] == ["2026-06-01-00-00.csv", "2026-06-01-00-00.svg"]
    assert paths[0].parent.name == "mapdemo"  # default "slug" output layout
    assert (paths[0].parent / "2026-06-01-00-00.join.json").is_file()
    # run() keeps its contract: the first output's path.
    assert sdk.run("mapdemo") == paths[0]
    # Library readers still find the CSV even though .svg sorts after it.
    assert len(sdk.latest_rows("mapdemo")) == 2
    assert sdk.info("mapdemo").row_count == 2
    sdk.validate("mapdemo")  # resolves the writers too


def test_dataset_without_outputs_keeps_single_default_format(tmp_path, fixed_clock, store):
    exporter = Exporter(store, fixed_clock)
    config = load_config(_write_dataset(tmp_path, ""))
    paths = exporter.export_outputs(config, [{"code": "AAA", "name": "A", "density": 1.0, "male": 50.0}])
    assert [path.suffix for path in paths] == [".csv"]
