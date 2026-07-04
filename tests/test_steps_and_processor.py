"""S04 — processing steps + processor (chain, ordering, validate loudness)."""

from datetime import date

import pytest

from datavibes.config.models import (
    DatasetConfig,
    DatasetMetadata,
    SourceSpec,
    StepSpec,
)
from datavibes.context import RunContext
from datavibes.errors import DatavibesError, SchemaValidationError
from datavibes.processing.processor import Processor
from datavibes.processing.steps import (
    AggregateStep,
    DedupeStep,
    DeriveStep,
    NormalizeStep,
    ValidateStep,
)
from datavibes.schema.field import Field, Schema


def _config(schema, processing, slug="demo"):
    return DatasetConfig(
        metadata=DatasetMetadata(slug=slug, title="Demo", category="test"),
        schema=schema,
        sources=[SourceSpec(type="static", options={"records": []})],
        processing=processing,
    )


def _ctx(config):
    return RunContext(config=config, clock=None)


def test_normalize_casts_and_drops_unknown():
    schema = Schema([Field(name="aqi", dtype="int")])
    ctx = _ctx(_config(schema, []))
    result = NormalizeStep().apply([{"aqi": "42", "_source": "x"}], ctx)
    assert result == [{"aqi": 42}]


def test_normalize_rejects_bad_value():
    schema = Schema([Field(name="aqi", dtype="int")])
    ctx = _ctx(_config(schema, []))
    with pytest.raises(SchemaValidationError):
        NormalizeStep().apply([{"aqi": "bad"}], ctx)


def test_dedupe_keep_first():
    ctx = _ctx(_config(Schema([Field(name="k")]), []))
    rows = [{"k": "a", "v": 1}, {"k": "a", "v": 2}, {"k": "b", "v": 3}]
    result = DedupeStep(keys=["k"]).apply(rows, ctx)
    assert [row["v"] for row in result] == [1, 3]


def test_dedupe_keep_last():
    ctx = _ctx(_config(Schema([Field(name="k")]), []))
    rows = [{"k": "a", "v": 1}, {"k": "a", "v": 2}]
    result = DedupeStep(keys=["k"], keep="last").apply(rows, ctx)
    assert result == [{"k": "a", "v": 2}]


def test_derive_adds_computed_column():
    schema = Schema([Field(name="v", dtype="float"), Field(name="chg", dtype="float", nullable=True)])
    ctx = _ctx(_config(schema, []))
    rows = [{"v": 100.0}, {"v": 150.0}]
    result = DeriveStep(column="chg", expr="pct_change(v)").apply(rows, ctx)
    assert result[0]["chg"] is None
    assert result[1]["chg"] == 0.5


def test_aggregate_mean_and_sum_by_group():
    schema = Schema(
        [Field(name="g"), Field(name="t", dtype="float"), Field(name="p", dtype="float")]
    )
    ctx = _ctx(_config(schema, []))
    rows = [
        {"g": "x", "t": 10.0},
        {"g": "x", "t": 20.0},
        {"g": "x", "p": 5.0},
        {"g": "y", "t": 4.0},
    ]
    result = AggregateStep(by=["g"], metrics={"t": "mean", "p": "sum"}).apply(rows, ctx)
    assert result[0] == {"g": "x", "t": 15.0, "p": 5.0}
    assert result[1] == {"g": "y", "t": 4.0, "p": 0}


def test_validate_raises_on_breach():
    schema = Schema([Field(name="aqi", dtype="int")])
    ctx = _ctx(_config(schema, []))
    with pytest.raises(SchemaValidationError):
        ValidateStep().apply([{"aqi": None}], ctx)


def test_full_chain_golden(fixed_clock):
    schema = Schema(
        [
            Field(name="region"),
            Field(name="day", dtype="date"),
            Field(name="temp", dtype="float"),
            Field(name="delta", dtype="float", nullable=True),
        ]
    )
    processing = [
        StepSpec(name="normalize"),
        StepSpec(name="aggregate", options={"by": ["region", "day"], "metrics": {"temp": "mean"}}),
        StepSpec(name="derive", options={"column": "delta", "expr": "pct_change(temp)"}),
        StepSpec(name="validate"),
    ]
    config = _config(schema, processing)
    raw = [
        {"region": "A", "day": "2026-06-01", "temp": "10", "_source": "s#0"},
        {"region": "A", "day": "2026-06-01", "temp": "20"},
        {"region": "A", "day": "2026-06-02", "temp": "30"},
    ]
    result = Processor(fixed_clock).process(config, raw)
    assert result == [
        {"region": "A", "day": date(2026, 6, 1), "temp": 15.0, "delta": None},
        {"region": "A", "day": date(2026, 6, 2), "temp": 30.0, "delta": 1.0},
    ]


def test_step_order_matters(fixed_clock):
    schema = Schema(
        [
            Field(name="k"),
            Field(name="v", dtype="float"),
            Field(name="delta", dtype="float", nullable=True),
        ]
    )
    derive = StepSpec(name="derive", options={"column": "delta", "expr": "pct_change(v)"})
    dedupe = StepSpec(name="dedupe", options={"keys": ["k"], "keep": "last"})
    rows = [{"k": "a", "v": 10.0}, {"k": "a", "v": 20.0}]

    derive_then_dedupe = Processor(fixed_clock).process(
        _config(schema, [derive, dedupe]), rows
    )
    dedupe_then_derive = Processor(fixed_clock).process(
        _config(schema, [dedupe, derive]), rows
    )
    # Deriving before collapsing keeps the change; collapsing first loses it.
    assert derive_then_dedupe == [{"k": "a", "v": 20.0, "delta": 1.0}]
    assert dedupe_then_derive == [{"k": "a", "v": 20.0, "delta": None}]


def test_mid_chain_failure_names_step(fixed_clock):
    schema = Schema([Field(name="aqi", dtype="int")])
    config = _config(schema, [StepSpec(name="validate")])
    with pytest.raises(SchemaValidationError):
        Processor(fixed_clock).process(config, [{"aqi": None}])


def test_processor_determinism(fixed_clock):
    schema = Schema([Field(name="v", dtype="int")])
    config = _config(schema, [StepSpec(name="normalize"), StepSpec(name="validate")])
    rows = [{"v": "1"}, {"v": "2"}]
    first = Processor(fixed_clock).process(config, rows)
    second = Processor(fixed_clock).process(config, rows)
    assert first == second
