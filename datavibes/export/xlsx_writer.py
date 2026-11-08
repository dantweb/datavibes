"""``xlsx`` writer — an Excel workbook: the data, pivots with native charts, and notes.

Sheets, in order:

* ``data`` — every schema column, one row per record (the same table as the CSV);
* one sheet per ``pivots`` entry — ``index`` down, one column per distinct
  ``columns`` value, cells = ``values``; ``index_range: [low, high]`` adds an
  (empty) row for every integer key in the range; with ``chart`` set, a native Excel
  scatter-with-lines chart (numeric x axis, so a fixed ``x_range`` such as
  1950–2025 is honoured and gaps stay gaps);
* ``About`` — title, attribution, licence and any ``notes`` lines.

``openpyxl`` is optional (``pip install 'datavibes[xlsx]'``); without it the
writer fails with a clear message, like the parquet writer. The workbook's
creation time is pinned so the same rows always produce the same bytes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from datavibes.errors import ConfigError, DatavibesError
from datavibes.export.writers import _cell
from datavibes.interfaces import Writer
from datavibes.registry import register_writer
from datavibes.schema.field import Schema

PINNED_TIMESTAMP = datetime(2000, 1, 1)
HEADER_FILL = "E8E6DF"


@register_writer("xlsx")
class XlsxWriter(Writer):
    def __init__(
        self,
        pivots: list[dict] | None = None,
        title: str = "",
        notes: list[str] | None = None,
        attribution: str = "",
        license: str = "",
    ):
        self.pivots = [self._check_pivot(spec) for spec in (pivots or [])]
        self.title = title
        self.notes = list(notes or [])
        self.attribution = attribution
        self.license = license

    @staticmethod
    def _check_pivot(spec: dict) -> dict:
        missing = [key for key in ("sheet", "index", "columns", "values") if not spec.get(key)]
        if missing:
            raise ConfigError(f"xlsx pivot needs {', '.join(missing)}")
        return spec

    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path:
        openpyxl = _require_openpyxl()
        workbook = openpyxl.Workbook()
        self._write_data(workbook.active, rows, schema)
        for spec in self.pivots:
            self._write_pivot(workbook.create_sheet(spec["sheet"][:31]), rows, spec)
        self._write_about(workbook.create_sheet("About"), schema)
        workbook.properties.created = PINNED_TIMESTAMP
        workbook.properties.modified = PINNED_TIMESTAMP
        dest.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(dest)
        return dest

    # ------------------------------------------------------------- sheets
    def _write_data(self, sheet, rows: list[dict], schema: Schema) -> None:
        sheet.title = "data"
        columns = schema.column_names()
        sheet.append(columns)
        for row in rows:
            sheet.append([_cell(row.get(name)) for name in columns])
        _style_header(sheet, len(columns))
        sheet.freeze_panes = "A2"

    def _write_pivot(self, sheet, rows: list[dict], spec: dict) -> None:
        index, columns, values = spec["index"], spec["columns"], spec["values"]
        keys = _ordered(row.get(index) for row in rows)
        if spec.get("index_range"):  # e.g. every year 1950–2025, empty where no data
            low, high = (int(bound) for bound in spec["index_range"])
            keys = sorted(set(keys) | set(range(low, high + 1)))
        series = spec.get("order") or _ordered(row.get(columns) for row in rows)
        cells = {(row.get(index), row.get(columns)): row.get(values) for row in rows}
        sheet.append([index, *series])
        for key in keys:
            sheet.append([key, *(cells.get((key, name)) for name in series)])
        _style_header(sheet, len(series) + 1)
        sheet.freeze_panes = "B2"
        if spec.get("chart"):
            self._add_chart(sheet, spec, len(keys), len(series))

    def _add_chart(self, sheet, spec: dict, key_count: int, series_count: int) -> None:
        from openpyxl.chart import Reference, ScatterChart, Series

        options = spec["chart"] if isinstance(spec["chart"], dict) else {}
        chart = ScatterChart()
        chart.title = options.get("title") or spec["values"]
        chart.style = 2
        chart.x_axis.title = options.get("x_title") or spec["index"]
        chart.y_axis.title = options.get("y_title") or spec["values"]
        chart.height, chart.width = 14, 28
        if options.get("x_range"):
            chart.x_axis.scaling.min, chart.x_axis.scaling.max = options["x_range"]
        if options.get("log_y"):
            chart.y_axis.scaling.logBase = 10
        # openpyxl hides axes by default since 3.1; a chart without axes is unreadable.
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        x_values = Reference(sheet, min_col=1, min_row=2, max_row=key_count + 1)
        for offset in range(series_count):
            column = offset + 2
            data = Reference(sheet, min_col=column, min_row=1, max_row=key_count + 1)
            line = Series(data, x_values, title_from_data=True)
            line.marker.symbol = "none"
            line.smooth = False
            chart.series.append(line)
        sheet.add_chart(chart, options.get("anchor", f"{_column_letter(series_count + 3)}2"))

    def _write_about(self, sheet, schema: Schema) -> None:
        lines = [("Title", self.title), ("Attribution", self.attribution),
                 ("Licence", self.license)]
        for label, value in lines:
            if value:
                sheet.append([label, value])
        for note in self.notes:
            sheet.append(["Note", note])
        sheet.append([])
        sheet.append(["Column", "Type", "Unit", "Description"])
        for field in schema.fields:
            sheet.append([field.name, field.dtype, field.unit or "", field.description or ""])
        sheet.column_dimensions["A"].width = 24
        sheet.column_dimensions["B"].width = 110


def _require_openpyxl():
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:
        raise DatavibesError(
            "xlsx export requires the optional 'openpyxl' dependency; "
            "install it with: pip install 'datavibes[xlsx]'"
        ) from exc
    return openpyxl


def _ordered(values) -> list:
    seen: list = []
    for value in values:
        if value is not None and value not in seen:
            seen.append(value)
    return sorted(seen, key=lambda item: (str(type(item)), item))


def _style_header(sheet, width: int) -> None:
    from openpyxl.styles import Font, PatternFill

    for column in range(1, width + 1):
        cell = sheet.cell(row=1, column=column)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index)
