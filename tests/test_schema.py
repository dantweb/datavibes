"""S02 — Field / Schema coercion, validation, and column ordering."""

from datetime import date

import pytest

from datavibes.errors import SchemaValidationError
from datavibes.schema.field import Field, Schema


def _schema() -> Schema:
    return Schema(
        fields=[
            Field(name="city", dtype="str"),
            Field(name="aqi", dtype="int"),
            Field(name="ratio", dtype="float", nullable=True),
            Field(name="active", dtype="bool"),
            Field(name="day", dtype="date"),
        ]
    )


def test_column_names_preserve_declared_order():
    assert _schema().column_names() == ["city", "aqi", "ratio", "active", "day"]


def test_coerce_casts_each_dtype():
    coerced = _schema().coerce(
        {
            "city": "Berlin",
            "aqi": "42",
            "ratio": "1.5",
            "active": "true",
            "day": "2026-06-01",
        }
    )
    assert coerced == {
        "city": "Berlin",
        "aqi": 42,
        "ratio": 1.5,
        "active": True,
        "day": date(2026, 6, 1),
    }


def test_coerce_nullable_accepts_empty():
    coerced = _schema().coerce(
        {"city": "X", "aqi": 1, "ratio": "", "active": "no", "day": "2026-01-01"}
    )
    assert coerced["ratio"] is None


def test_coerce_non_nullable_empty_raises():
    with pytest.raises(SchemaValidationError):
        Schema(fields=[Field(name="aqi", dtype="int")]).coerce({"aqi": ""})


def test_coerce_rejects_unknown_column():
    with pytest.raises(SchemaValidationError):
        Schema(fields=[Field(name="aqi", dtype="int")]).coerce({"aqi": 1, "junk": 2})


def test_coerce_bad_value_raises():
    with pytest.raises(SchemaValidationError):
        Schema(fields=[Field(name="aqi", dtype="int")]).coerce({"aqi": "not-a-number"})


def test_validate_passes_clean_rows():
    schema = _schema()
    schema.validate(
        [
            {
                "city": "Berlin",
                "aqi": 42,
                "ratio": None,
                "active": True,
                "day": date(2026, 6, 1),
            }
        ]
    )


def test_validate_flags_null_in_non_nullable():
    schema = Schema(fields=[Field(name="aqi", dtype="int")])
    with pytest.raises(SchemaValidationError):
        schema.validate([{"aqi": None}])


def test_validate_flags_wrong_dtype():
    schema = Schema(fields=[Field(name="aqi", dtype="int")])
    with pytest.raises(SchemaValidationError):
        schema.validate([{"aqi": "42"}])


def test_unsupported_dtype_rejected():
    with pytest.raises(SchemaValidationError):
        Field(name="x", dtype="complex")


def test_duplicate_columns_rejected():
    with pytest.raises(SchemaValidationError):
        Schema(fields=[Field(name="a"), Field(name="a")])
