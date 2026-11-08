"""S05 — writers + exporter (schema-ordered, byte-stable, contract path)."""

import json
from datetime import date

import pytest

from datavibes.config.models import DatasetConfig, DatasetMetadata, SourceSpec
from datavibes.errors import UnknownStrategyError
from datavibes.export.exporter import Exporter
from datavibes.export.writers import CsvWriter, JsonWriter
from datavibes.registry import resolve_writer
from datavibes.schema.field import Field, Schema


def _schema():
    return Schema([Field(name="city"), Field(name="aqi", dtype="int")])


def test_csv_header_follows_schema_order_not_row_order(tmp_path):
    dest = tmp_path / "out.csv"
    # Row dict deliberately reversed key order.
    CsvWriter().write([{"aqi": 42, "city": "Berlin"}], _schema(), dest)
    assert dest.read_text(encoding="utf-8") == "city,aqi\nBerlin,42\n"


def test_csv_matches_air_quality_sample_shape(tmp_path):
    dest = tmp_path / "out.csv"
    CsvWriter().write([{"city": "Berlin", "aqi": 42}], _schema(), dest)
    # Mirrors var/dataset/.../air-quality-*/2026-06-01-00-00.csv
    assert dest.read_text(encoding="utf-8") == "city,aqi\nBerlin,42\n"


def test_csv_is_byte_identical_across_runs(tmp_path):
    schema = _schema()
    rows = [{"city": "Berlin", "aqi": 42}, {"city": "Paris", "aqi": 7}]
    first = CsvWriter().write(rows, schema, tmp_path / "a.csv").read_bytes()
    second = CsvWriter().write(rows, schema, tmp_path / "b.csv").read_bytes()
    assert first == second


def test_csv_renders_none_as_empty_and_dates_iso(tmp_path):
    schema = Schema([Field(name="day", dtype="date"), Field(name="v", dtype="float", nullable=True)])
    dest = tmp_path / "out.csv"
    CsvWriter().write([{"day": date(2026, 6, 1), "v": None}], schema, dest)
    assert dest.read_text(encoding="utf-8") == "day,v\n2026-06-01,\n"


def test_json_keys_are_schema_ordered(tmp_path):
    dest = tmp_path / "out.json"
    JsonWriter().write([{"aqi": 42, "city": "Berlin"}], _schema(), dest)
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert list(payload[0].keys()) == ["city", "aqi"]


def test_unknown_writer_names_the_format():
    with pytest.raises(UnknownStrategyError) as info:
        resolve_writer("ods")
    assert "ods" in str(info.value)


def test_exporter_writes_to_contract_path(store, fixed_clock):
    config = DatasetConfig(
        metadata=DatasetMetadata(slug="air-quality", title="AQ", category="environment"),
        schema=_schema(),
        sources=[SourceSpec(type="static", options={"records": []})],
    )
    rows = [{"city": "Berlin", "aqi": 42}]
    path = Exporter(store, fixed_clock).export(config, rows)
    parts = path.parts
    assert parts[-1] == "2026-06-01-00-00.csv"
    assert parts[-2] == "air-quality"  # output/<slug>/<ts>.csv (slug layout)
    assert parts[-3] == "output"
    assert path.read_text(encoding="utf-8") == "city,aqi\nBerlin,42\n"


def test_exporter_is_idempotent(store, fixed_clock):
    config = DatasetConfig(
        metadata=DatasetMetadata(slug="air-quality", title="AQ", category="environment"),
        schema=_schema(),
        sources=[SourceSpec(type="static", options={"records": []})],
    )
    rows = [{"city": "Berlin", "aqi": 42}]
    exporter = Exporter(store, fixed_clock)
    first = exporter.export(config, rows)
    first_bytes = first.read_bytes()
    second = exporter.export(config, rows)
    assert first == second
    assert second.read_bytes() == first_bytes
