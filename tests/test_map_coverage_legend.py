"""S15 — coverage legends: how many items are on a map, how many were left out and why."""

import json
import re
from pathlib import Path

import pytest

from datavibes.config.models import DatasetConfig, DatasetMetadata, OutputSpec, SourceSpec, StepSpec
from datavibes.context import FixedClock
from datavibes.export.exporter import Exporter
from datavibes.interfaces import Writer
from datavibes.processing.processor import Processor
from datavibes.provenance import Exclusion, Provenance
from datavibes.registry import resolve_writer
from datavibes.schema.field import Field, Schema

FIXTURES = Path(__file__).parent / "fixtures" / "geometry"


def _config(processing=(), outputs=()):
    return DatasetConfig(
        metadata=DatasetMetadata(slug="demo", title="Demo", category="test"),
        schema=Schema([Field(name="name"), Field(name="value", dtype="float", nullable=True),
                       Field(name="other", dtype="float", nullable=True)]),
        sources=[SourceSpec(type="static")],
        processing=list(processing),
        outputs=list(outputs),
    )


ROWS = [
    {"name": "a", "value": 1.0, "other": 1.0},
    {"name": "b", "value": None, "other": 1.0},
    {"name": "c", "value": None, "other": None},
    {"name": "d", "value": 2.0, "other": None},
]
FILTERS = [
    StepSpec(name="filter", options={"when": {"column": "value", "not_null": True}, "reason": "no value"}),
    StepSpec(name="filter", options={"when": {"column": "other", "not_null": True}, "reason": "no other"}),
]


# ------------------------------------------------------------ processor trace
def test_processor_records_exclusions_per_reasoned_filter(fixed_clock):
    rows, provenance = Processor(fixed_clock).process_with_provenance(_config(FILTERS), ROWS)
    assert [row["name"] for row in rows] == ["a"]
    assert provenance.exclusions == (Exclusion("no value", 2), Exclusion("no other", 1))
    assert provenance.total_excluded == 3


def test_filters_without_a_reason_are_counted_as_filtered(fixed_clock):
    steps = [StepSpec(name="filter", options={"when": {"column": "value", "not_null": True}})]
    _, provenance = Processor(fixed_clock).process_with_provenance(_config(steps), ROWS)
    assert provenance.exclusions == (Exclusion("filtered out", 2),)


def test_process_keeps_its_plain_signature(fixed_clock):
    assert [row["name"] for row in Processor(fixed_clock).process(_config(FILTERS), ROWS)] == ["a"]


# ---------------------------------------------------------- exporter → writers
class _RecordingWriter(Writer):
    seen: list = []

    def write(self, rows, schema, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x", encoding="utf-8")
        return dest

    def attach_provenance(self, provenance):
        _RecordingWriter.seen.append(provenance)


def test_exporter_hands_provenance_to_every_writer(tmp_path, fixed_clock, store, monkeypatch):
    from datavibes import registry

    monkeypatch.setitem(registry.WRITER_REGISTRY, "recording", _RecordingWriter)
    provenance = Provenance(exclusions=(Exclusion("no value", 2),))
    Exporter(store, fixed_clock).export_outputs(
        _config(outputs=[OutputSpec(name="recording")]), [], provenance=provenance)
    assert _RecordingWriter.seen[-1] is provenance


def test_writers_ignore_provenance_by_default():
    from datavibes.export.writers import CsvWriter

    CsvWriter().attach_provenance(Provenance())  # no-op, no error


# ------------------------------------------------------------- legend content
SCHEMA = Schema([Field(name="name"), Field(name="lat", dtype="float"), Field(name="lon", dtype="float"),
                 Field(name="population", dtype="int"), Field(name="density", dtype="float")])
DOTS = [
    {"name": "One", "lat": 45.0, "lon": 5.0, "population": 100000, "density": 100.0},
    {"name": "Two", "lat": 10.0, "lon": 10.0, "population": 2000000, "density": 5000.0},
]


def _dot_writer(provenance=None):
    writer = resolve_writer("svg-dot-map", {
        "geometry": "fixture-countries", "geometry_manifest": str(FIXTURES / "manifest.yaml"),
        "latitude_column": "lat", "longitude_column": "lon", "size_column": "population",
        "item_label": "cities",
        "color_scale": {"type": "spectral-density", "value_column": "density"},
    })
    if provenance is not None:
        writer.attach_provenance(provenance)
    return writer


def _text(svg: str) -> str:
    return " ".join(re.findall(r">([^<>]+)</text>", svg))


def test_dot_map_legend_counts_shown_and_excluded_items(tmp_path):
    provenance = Provenance(exclusions=(Exclusion("no usable density", 762), Exclusion("no country data", 19)))
    dest = _dot_writer(provenance).write(DOTS, SCHEMA, tmp_path / "2026-06-01-00-00.svg")
    text = _text(dest.read_text(encoding="utf-8"))
    assert "Coverage" in text
    assert "Cities shown: 2 of 783" in text
    assert "Not included: 781 — no usable density: 762 · no country data: 19" in text
    report = json.loads((tmp_path / "2026-06-01-00-00.join.json").read_text(encoding="utf-8"))
    assert report["excluded"] == {"no usable density": 762, "no country data": 19}


def test_dot_map_without_exclusions_says_all_are_shown(tmp_path):
    text = _text(_dot_writer().write(DOTS, SCHEMA, tmp_path / "m.svg").read_text(encoding="utf-8"))
    assert "Cities shown: 2 of 2" in text
    assert "Not included: none" in text


def test_choropleth_legend_counts_coloured_missing_and_undrawn(tmp_path):
    schema = Schema([Field(name="code"), Field(name="density", dtype="float", nullable=True)])
    rows = [{"code": "AAA", "density": 1.0}, {"code": "BBB", "density": None},
            {"code": "ZZZ", "density": 5.0}]
    writer = resolve_writer("svg-map", {
        "geometry": "fixture-countries", "geometry_manifest": str(FIXTURES / "manifest.yaml"),
        "key_column": "code", "item_label": "countries",
        "color_scale": {"type": "spectral-density", "value_column": "density"},
    })
    text = _text(writer.write(rows, schema, tmp_path / "m.svg").read_text(encoding="utf-8"))
    assert "Countries coloured: 1 of 4 drawn" in text
    assert "Without data (grey): 3" in text
    assert "In the data but not drawn (too small at this scale or outside the map): 1" in text
