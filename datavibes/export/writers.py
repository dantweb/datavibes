"""Format writers — the schema decides columns, the writer only serialises."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path

from datavibes.errors import DatavibesError
from datavibes.interfaces import Writer
from datavibes.registry import register_writer
from datavibes.schema.field import Schema


def _cell(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@register_writer("csv")
class CsvWriter(Writer):
    """Default writer — matches the shape the ``dataset`` plugin serves."""

    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path:
        columns = schema.column_names()
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row.get(name) is None else _cell(row.get(name)) for name in columns])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(buffer.getvalue(), encoding="utf-8")
        return dest


@register_writer("json")
class JsonWriter(Writer):
    """JSON array of objects with schema-ordered keys."""

    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path:
        columns = schema.column_names()
        payload = [
            {name: _cell(row.get(name)) for name in columns} for row in rows
        ]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dest


@register_writer("parquet")
class ParquetWriter(Writer):
    """Columnar export — optional dependency, degrades with a clear message."""

    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path:
        try:
            import pyarrow  # type: ignore
            import pyarrow.parquet as parquet  # type: ignore
        except ImportError as exc:
            raise DatavibesError(
                "parquet export requires the optional 'pyarrow' dependency; "
                "install it with: pip install 'datavibes[parquet]'"
            ) from exc

        columns = schema.column_names()
        table_data = {
            name: [_cell(row.get(name)) for row in rows] for name in columns
        }
        table = pyarrow.table(table_data)
        dest.parent.mkdir(parents=True, exist_ok=True)
        parquet.write_table(table, str(dest))
        return dest
