"""``Field`` / ``Schema`` — the single source of truth for output columns.

The schema decides which columns exist, their dtypes, nullability, and their
order. The exporter never guesses columns; it asks the schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from datavibes.errors import SchemaValidationError

SUPPORTED_DTYPES = ("str", "int", "float", "bool", "date")

_TRUE_STRINGS = {"true", "1", "yes", "y", "t"}
_FALSE_STRINGS = {"false", "0", "no", "n", "f"}


@dataclass(frozen=True)
class Field:
    """A single typed column of the output dataset."""

    name: str
    dtype: str = "str"
    nullable: bool = False
    unit: str | None = None
    description: str | None = None
    transform: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaValidationError("field name must be non-empty")
        if self.dtype not in SUPPORTED_DTYPES:
            raise SchemaValidationError(
                f"field '{self.name}': unsupported dtype '{self.dtype}' "
                f"(expected one of {', '.join(SUPPORTED_DTYPES)})"
            )

    def coerce(self, value: Any) -> Any:
        """Cast ``value`` to this field's dtype; raise on an invalid value."""
        if value is None or value == "":
            if self.nullable:
                return None
            raise SchemaValidationError(
                f"field '{self.name}' is not nullable but received an empty value"
            )
        try:
            return _COERCERS[self.dtype](value)
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"field '{self.name}': cannot coerce {value!r} to {self.dtype}"
            ) from exc


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE_STRINGS:
        return True
    if text in _FALSE_STRINGS:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


_COERCERS = {
    "str": lambda value: str(value),
    "int": lambda value: int(value),
    "float": lambda value: float(value),
    "bool": _coerce_bool,
    "date": _coerce_date,
}


@dataclass
class Schema:
    """An ordered list of :class:`Field` — the dataset's output contract."""

    fields: list[Field] = field(default_factory=list)

    def __post_init__(self) -> None:
        names = [column.name for column in self.fields]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise SchemaValidationError(
                f"duplicate column(s): {', '.join(sorted(duplicates))}"
            )

    def column_names(self) -> list[str]:
        """Ordered column names — the single source of output column order."""
        return [column.name for column in self.fields]

    def field_for(self, name: str) -> Field:
        for column in self.fields:
            if column.name == name:
                return column
        raise SchemaValidationError(f"unknown column '{name}'")

    def coerce(self, row: dict) -> dict:
        """Cast every declared column of ``row`` to its dtype, in schema order."""
        unknown = set(row) - set(self.column_names())
        if unknown:
            raise SchemaValidationError(
                f"row has unknown column(s): {', '.join(sorted(unknown))}"
            )
        coerced: dict = {}
        for column in self.fields:
            coerced[column.name] = column.coerce(row.get(column.name))
        return coerced

    def validate(self, rows: list[dict]) -> None:
        """Assert every row matches names, dtypes, and nullability."""
        expected = set(self.column_names())
        for index, row in enumerate(rows):
            missing = expected - set(row)
            if missing:
                raise SchemaValidationError(
                    f"row {index} missing column(s): {', '.join(sorted(missing))}"
                )
            unknown = set(row) - expected
            if unknown:
                raise SchemaValidationError(
                    f"row {index} has unknown column(s): {', '.join(sorted(unknown))}"
                )
            for column in self.fields:
                self._validate_cell(index, column, row[column.name])

    def _validate_cell(self, index: int, column: Field, value: Any) -> None:
        if value is None:
            if not column.nullable:
                raise SchemaValidationError(
                    f"row {index} column '{column.name}' is null but not nullable"
                )
            return
        expected_type = _RUNTIME_TYPES[column.dtype]
        if isinstance(value, bool) and column.dtype != "bool":
            raise SchemaValidationError(
                f"row {index} column '{column.name}' expected {column.dtype}, got bool"
            )
        if not isinstance(value, expected_type):
            raise SchemaValidationError(
                f"row {index} column '{column.name}' expected {column.dtype}, "
                f"got {type(value).__name__}"
            )


_RUNTIME_TYPES: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "date": date,
}
