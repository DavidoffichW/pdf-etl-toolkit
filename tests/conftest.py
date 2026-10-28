from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from capabilities import detect_capabilities  # noqa: E402
from runplan import build_run_plan  # noqa: E402


def build_pdf(page_specs: list[dict[str, Any]]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)

    for specification in page_specs:
        width, height = 420.0, 320.0
        page = writer.add_blank_page(width=width, height=height)
        commands: list[str] = ["0 G", "0.75 w"]
        tables = specification.get("tables")
        if tables is None:
            tables = [specification] if specification.get("rows") else []

        for table in tables:
            rows = table.get("rows", [])
            grid = bool(table.get("grid", False))
            x0 = float(table.get("x0", 35.0))
            y0 = float(table.get("y0", 45.0))
            cell_width = float(table.get("cell_width", 105.0))
            cell_height = float(table.get("cell_height", 28.0))
            columns = max((len(row) for row in rows), default=0)
            if grid and rows and columns:
                for row_index in range(len(rows) + 1):
                    top = y0 + row_index * cell_height
                    y = height - top
                    commands.append(f"{x0} {y} m {x0 + columns * cell_width} {y} l S")
                for column_index in range(columns + 1):
                    x = x0 + column_index * cell_width
                    top = height - y0
                    bottom = height - (y0 + len(rows) * cell_height)
                    commands.append(f"{x} {top} m {x} {bottom} l S")
            for row_index, row in enumerate(rows):
                for column_index, value in enumerate(row):
                    text = _escape_pdf_text(str(value))
                    x = x0 + column_index * cell_width + 7
                    y = height - (y0 + row_index * cell_height + 18)
                    commands.append(f"BT /F1 10 Tf 1 0 0 1 {x} {y} Tm ({text}) Tj ET")

        if not tables:
            text = _escape_pdf_text(str(specification.get("text", "blank")))
            commands.append(f"BT /F1 10 Tf 1 0 0 1 40 260 Tm ({text}) Tj ET")

        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        content = DecodedStreamObject()
        content.set_data(("\n".join(commands) + "\n").encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(content)
        rotation = int(specification.get("rotation", 0))
        if rotation:
            page.rotate(rotation)

    writer.add_metadata({"/Title": "Synthetic PDF fixture", "/Producer": "pypdf tests"})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


@pytest.fixture
def plan():
    return build_run_plan(detect_capabilities())


@pytest.fixture
def plain_pdf() -> bytes:
    return build_pdf([{"text": "first"}, {"text": "second"}, {"text": "third"}])


@pytest.fixture
def grid_pdf() -> bytes:
    return build_pdf(
        [
            {
                "grid": True,
                "rows": [
                    ["Name", "Qty", "Price"],
                    ["Alpha", "2", "10"],
                    ["Beta", "3", "11"],
                ],
            },
            {
                "grid": True,
                "rows": [
                    ["Code", "Jan", "Feb"],
                    ["X", "4", "5"],
                    ["Y", "6", "7"],
                ],
            },
        ]
    )


@pytest.fixture
def text_table_pdf() -> bytes:
    return build_pdf(
        [
            {
                "rows": [
                    ["Name", "Qty", "Price"],
                    ["Alpha", "2", "10"],
                    ["Beta", "3", "11"],
                ]
            }
        ]
    )


@pytest.fixture
def multiple_tables_pdf() -> bytes:
    return build_pdf(
        [
            {
                "tables": [
                    {
                        "grid": True,
                        "x0": 25,
                        "y0": 35,
                        "cell_width": 55,
                        "rows": [["A", "B"], ["1", "2"], ["3", "4"]],
                    },
                    {
                        "grid": True,
                        "x0": 235,
                        "y0": 160,
                        "cell_width": 55,
                        "rows": [["C", "D"], ["5", "6"], ["7", "8"]],
                    },
                ]
            }
        ]
    )


@pytest.fixture
def blank_pdf() -> bytes:
    return build_pdf([{"text": ""}])


@pytest.fixture
def rotated_pdf() -> bytes:
    return build_pdf([{"text": "rotated", "rotation": 90}, {"text": "normal"}])


@pytest.fixture
def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
