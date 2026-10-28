from __future__ import annotations

import csv
import json
import zipfile
from io import BytesIO, StringIO

import pytest
from openpyxl import load_workbook

import export


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+SUM(1,2)", "'+SUM(1,2)"),
        ("-1+2", "'-1+2"),
        ("@SUM(1,2)", "'@SUM(1,2)"),
        (" \t=1+1", "' \t=1+1"),
        ("\r@SUM(1,2)", "'\r@SUM(1,2)"),
        ("ordinary text", "ordinary text"),
        ("-1", "-1"),
        ("-1.25", "-1.25"),
        ("-1e3", "-1e3"),
    ],
)
def test_spreadsheet_escape_policy(source, expected):
    assert export.escape_spreadsheet_value(source) == expected


def _table(values: list[str]) -> export.ExportTable:
    return export.ExportTable(
        schema_headers=["col_1"],
        rows=[
            export.ExportRow("file", 0, "candidate", index, [value])
            for index, value in enumerate(values)
        ],
    )


def test_csv_and_xlsx_escape_formula_content_but_jsonl_preserves_source():
    values = ["=1+1", "+SUM(1,2)", "-1+2", "@SUM(1,2)", "\t=2", "text", "-42"]
    table = _table(values)

    csv_rows = list(csv.reader(StringIO(export.build_results_csv_bytes(table).decode("utf-8"))))
    assert [row[-1] for row in csv_rows[1:]] == [
        "'=1+1",
        "'+SUM(1,2)",
        "'-1+2",
        "'@SUM(1,2)",
        "'\t=2",
        "text",
        "-42",
    ]

    jsonl = [json.loads(line) for line in export.build_results_jsonl_bytes(table).splitlines()]
    assert [row["row"]["col_1"] for row in jsonl] == values

    workbook = load_workbook(BytesIO(export.maybe_build_xlsx_bytes(table)), data_only=False)
    cells = [workbook["results"][f"E{row}"] for row in range(2, 9)]
    assert [cell.value for cell in cells] == [
        "'=1+1",
        "'+SUM(1,2)",
        "'-1+2",
        "'@SUM(1,2)",
        "'\t=2",
        "text",
        "-42",
    ]
    assert all(cell.data_type != "f" for cell in cells)


def test_export_schema_keeps_first_detected_row_as_data():
    table = export.ExportTable(
        schema_headers=["col_1", "col_2"],
        rows=[export.ExportRow("file", 0, "candidate", 0, ["Header A", "Header B"])],
    )
    rows = list(csv.reader(StringIO(export.build_results_csv_bytes(table).decode("utf-8"))))
    assert rows[0] == [
        "file_id",
        "page_index",
        "candidate_id",
        "row_index",
        "col_1",
        "col_2",
    ]
    assert rows[1][-2:] == ["Header A", "Header B"]


def test_xlsx_and_outer_zip_are_byte_reproducible():
    table = _table(["alpha", "=1+1"])
    xlsx_one = export.maybe_build_xlsx_bytes(table)
    xlsx_two = export.maybe_build_xlsx_bytes(table)
    assert xlsx_one == xlsx_two

    rows = [("file", 0, "candidate", 0, ["alpha"])]
    events = [{"timestamp": "first", "level": "INFO", "message": "stable"}]
    first = export.build_export_zip(
        table_headers=["col_1"],
        table_rows=rows,
        manifest={"files": []},
        events=events,
        include_xlsx=True,
    )
    second = export.build_export_zip(
        table_headers=["col_1"],
        table_rows=rows,
        manifest={"files": []},
        events=[{**events[0], "timestamp": "second"}],
        include_xlsx=True,
    )
    assert first == second
    with zipfile.ZipFile(BytesIO(first)) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert all(item.date_time == export.FIXED_ZIP_TIME for item in archive.infolist())
        assert json.loads(archive.read("events.jsonl"))["message"] == "stable"
        assert "timestamp" not in archive.read("events.jsonl").decode("utf-8")


def test_zip_rejects_unsafe_extra_member():
    with pytest.raises(ValueError, match="unsafe ZIP member"):
        export.build_export_zip(
            table_headers=[],
            table_rows=[],
            manifest={},
            events=[],
            include_xlsx=False,
            extra_members={"../escape": b"unsafe"},
        )
