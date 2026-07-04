"""S03 — Generator snapshots (merge, tagging, determinism, degrade-on-failure)."""

from datavibes.config.models import DatasetConfig, DatasetMetadata, SourceSpec
from datavibes.generator.generator import SOURCE_TAG_FIELD, Generator
from datavibes.interfaces import Source
from datavibes.registry import register_source
from datavibes.schema.field import Field, Schema


@register_source("test-emit")
class _EmitSource(Source):
    def __init__(self, records=None):
        self.records = records or []

    def fetch(self, ctx):
        return list(self.records)


@register_source("test-boom")
class _BoomSource(Source):
    def fetch(self, ctx):
        raise RuntimeError("source down")


def _config(sources):
    return DatasetConfig(
        metadata=DatasetMetadata(slug="demo", title="Demo", category="test"),
        schema=Schema(fields=[Field(name="a", dtype="int")]),
        sources=sources,
    )


def test_merges_sources_in_order_and_tags(store, fixed_clock):
    config = _config(
        [
            SourceSpec(type="test-emit", options={"records": [{"a": 1}]}),
            SourceSpec(type="test-emit", options={"records": [{"a": 2}]}),
        ]
    )
    snapshot = Generator(store, fixed_clock).generate(config)
    assert snapshot.row_count == 2
    assert [record["a"] for record in snapshot.records] == [1, 2]
    assert snapshot.records[0][SOURCE_TAG_FIELD] == "test-emit#0"
    assert snapshot.records[1][SOURCE_TAG_FIELD] == "test-emit#1"


def test_snapshot_is_byte_stable(store, fixed_clock):
    config = _config([SourceSpec(type="test-emit", options={"records": [{"a": 1}]})])
    first = Generator(store, fixed_clock).generate(config).path.read_bytes()
    second = Generator(store, fixed_clock).generate(config).path.read_bytes()
    assert first == second


def test_failing_source_degrades_not_aborts(store, fixed_clock):
    config = _config(
        [
            SourceSpec(type="test-boom"),
            SourceSpec(type="test-emit", options={"records": [{"a": 9}]}),
        ]
    )
    snapshot = Generator(store, fixed_clock).generate(config)
    assert snapshot.row_count == 1
    assert snapshot.records[0]["a"] == 9
    assert len(snapshot.failed_sources) == 1


def test_all_empty_sources_produce_valid_empty_snapshot(store, fixed_clock):
    config = _config([SourceSpec(type="test-emit", options={"records": []})])
    snapshot = Generator(store, fixed_clock).generate(config)
    assert snapshot.row_count == 0
    assert snapshot.path.read_text(encoding="utf-8") == ""
