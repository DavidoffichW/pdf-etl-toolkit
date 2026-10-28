from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
import pytest
from pypdf import PdfWriter


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from capabilities import detect_capabilities  # noqa: E402
from runplan import build_run_plan  # noqa: E402


def build_pdf(page_specs: list[dict[str, Any]]) -> bytes:
    with fitz.open() as document:
        for specification in page_specs:
            page = document.new_page(width=420, height=320)
            rows = specification.get("rows", [])
            grid = bool(specification.get("grid", False))
            x0, y0, cell_width, cell_height = 35.0, 45.0, 105.0, 28.0
            columns = max((len(row) for row in rows), default=0)
            if grid and rows and columns:
                for row_index in range(len(rows) + 1):
                    y = y0 + row_index * cell_height
                    page.draw_line((x0, y), (x0 + columns * cell_width, y))
                for column_index in range(columns + 1):
                    x = x0 + column_index * cell_width
                    page.draw_line((x, y0), (x, y0 + len(rows) * cell_height))
            for row_index, row in enumerate(rows):
                for column_index, text in enumerate(row):
                    page.insert_text(
                        (
                            x0 + column_index * cell_width + 7,
                            y0 + row_index * cell_height + 18,
                        ),
                        str(text),
                        fontsize=10,
                    )
            if not rows:
                page.insert_text((40, 60), str(specification.get("text", "blank")))
        return document.tobytes()


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
def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
