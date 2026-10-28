from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader

import extract
import workspace
from engine import Engine


def _texts(pdf_bytes: bytes) -> list[str]:
    return [(page.extract_text() or "").strip() for page in PdfReader(BytesIO(pdf_bytes)).pages]


def _candidate(file_id: str, page: int, provider: str, text: str) -> extract.TableCandidate:
    return extract.TableCandidate(
        candidate_id=f"{provider}-{page}",
        file_id=file_id,
        page_index=page,
        bbox=(0.0, 0.0, 10.0, 10.0),
        row_count=1,
        col_count=1,
        score=1.0,
        cells=[extract.TableCell(0, 0, text)],
        provider=provider,
    )


def test_ingest_merge_extract_and_delete(plan, plain_pdf):
    engine = Engine(plan)
    ingested, pages = engine.ingest("plain.pdf", plain_pdf)
    assert ingested.page_count == 3
    assert len(pages) == 3

    first = workspace._extract_pages(plain_pdf, 1, 1)
    third = workspace._extract_pages(plain_pdf, 3, 3)
    assert _texts(workspace._merge_pdfs([third, first])) == ["third", "first"]
    assert _texts(workspace._extract_pages(plain_pdf, 2, 3)) == ["second", "third"]
    assert _texts(workspace._delete_pages(plain_pdf, 2, 2)) == ["first", "third"]


def test_pypdf_operations_preserve_page_rotation_and_validity(plan, rotated_pdf):
    engine = Engine(plan)
    ingested, pages = engine.ingest("rotated.pdf", rotated_pdf)
    assert ingested.page_count == 2
    assert [(page.width, page.height) for page in pages] == [(420.0, 320.0), (420.0, 320.0)]

    reordered = workspace._merge_pdfs(
        [workspace._extract_pages(rotated_pdf, 2, 2), workspace._extract_pages(rotated_pdf, 1, 1)]
    )
    reader = PdfReader(BytesIO(reordered))
    assert len(reader.pages) == 2
    assert [page.rotation for page in reader.pages] == [0, 90]
    assert _texts(reordered) == ["normal", "rotated"]


@pytest.mark.parametrize("payload", [b"", b"not a PDF", b"%PDF-1.7\nmalformed"])
def test_invalid_pdf_is_rejected(plan, payload):
    with pytest.raises(Exception):
        Engine(plan).ingest("invalid.pdf", payload)


def test_encrypted_pdf_is_rejected(plan, encrypted_pdf):
    with pytest.raises(Exception):
        Engine(plan).ingest("encrypted.pdf", encrypted_pdf)


def test_all_slice_modes(plan):
    engine = Engine(plan)
    grid = [["h1", "h2"], ["a", "b"]]
    assert engine.slice_grid(grid, mode="table", row_1b=None, col_1b=None)[1] == grid
    assert engine.slice_grid(grid, mode="row", row_1b=2, col_1b=None)[1] == [["a", "b"]]
    assert engine.slice_grid(grid, mode="column", row_1b=None, col_1b=2)[1] == [["h2"], ["b"]]
    assert engine.slice_grid(grid, mode="cell", row_1b=2, col_1b=2)[1] == [["b"]]


def test_provider_fallback_is_applied_per_page(plan, monkeypatch):
    calls: list[tuple[str, tuple[int, ...]]] = []

    def preferred(file_id, data, pages):
        calls.append(("pdfplumber", tuple(pages)))
        return [_candidate(file_id, 0, "pdfplumber", "first")], []

    def fallback(file_id, data, pages):
        calls.append(("text_grid", tuple(pages)))
        return [_candidate(file_id, 1, "text_grid", "second")], []

    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 2)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(extract, "_detect_with_pdfplumber", preferred)
    monkeypatch.setattr(extract, "_detect_with_text_grid_heuristic", fallback)

    result = extract.detect_tables("file", b"synthetic", plan)
    assert result.status == "OK"
    assert [(item.page_index, item.provider) for item in result.candidates] == [
        (0, "pdfplumber"),
        (1, "text_grid"),
    ]
    assert calls == [("pdfplumber", (0, 1)), ("text_grid", (1,))]


def test_provider_initialization_failure_falls_back(plan, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 1)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(extract, "_detect_with_pdfplumber", failed)
    monkeypatch.setattr(
        extract,
        "_detect_with_text_grid_heuristic",
        lambda file_id, data, pages: ([_candidate(file_id, 0, "text_grid", "ok")], []),
    )

    result = extract.detect_tables("file", b"synthetic", plan)
    assert result.status == "PARTIAL"
    assert result.candidates[0].provider == "text_grid"
    assert "pdfplumber initialization failed" in result.errors[0]


def test_detection_distinguishes_failure_from_no_table(plan, monkeypatch):
    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 1)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(
        extract,
        "_detect_with_pdfplumber",
        lambda file_id, data, pages: ([], ["page failed"]),
    )
    monkeypatch.setattr(
        extract,
        "_detect_with_text_grid_heuristic",
        lambda file_id, data, pages: ([], ["fallback failed"]),
    )
    assert extract.detect_tables("file", b"synthetic", plan).status == "FAILED"

    monkeypatch.setattr(extract, "_detect_with_pdfplumber", lambda file_id, data, pages: ([], []))
    monkeypatch.setattr(
        extract,
        "_detect_with_text_grid_heuristic",
        lambda file_id, data, pages: ([], []),
    )
    assert extract.detect_tables("file", b"synthetic", plan).status == "NO_TABLE"


def test_real_detection_is_stable_and_records_provider(plan, grid_pdf):
    engine = Engine(plan)
    ingested, _ = engine.ingest("grid.pdf", grid_pdf)
    first = engine.detect_tables(ingested.file_id, grid_pdf)
    second = engine.detect_tables(ingested.file_id, grid_pdf)
    assert first.status in {"OK", "PARTIAL"}
    assert [candidate.candidate_id for candidate in first.candidates] == [
        candidate.candidate_id for candidate in second.candidates
    ]
    assert {candidate.page_index for candidate in first.candidates} == {0, 1}
    assert all(candidate.provider in {"pdfplumber", "text_grid"} for candidate in first.candidates)


def test_text_grid_fallback_extracts_ungridded_table(plan, text_table_pdf):
    engine = Engine(plan)
    ingested, _ = engine.ingest("text-table.pdf", text_table_pdf)
    result = engine.detect_tables(ingested.file_id, text_table_pdf)
    assert result.status in {"OK", "PARTIAL"}
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.provider == "text_grid"
    assert (candidate.row_count, candidate.col_count) == (3, 3)
    assert engine.candidate_to_grid(candidate) == [
        ["Name", "Qty", "Price"],
        ["Alpha", "2", "10"],
        ["Beta", "3", "11"],
    ]


def test_primary_provider_returns_multiple_tables_in_stable_order(plan, multiple_tables_pdf):
    engine = Engine(plan)
    ingested, _ = engine.ingest("two-tables.pdf", multiple_tables_pdf)
    result = engine.detect_tables(ingested.file_id, multiple_tables_pdf)
    assert result.status in {"OK", "PARTIAL"}
    assert len(result.candidates) == 2
    assert [candidate.provider for candidate in result.candidates] == [
        "pdfplumber",
        "pdfplumber",
    ]
    assert [engine.candidate_to_grid(candidate)[0] for candidate in result.candidates] == [
        ["A", "B"],
        ["C", "D"],
    ]


def test_partial_page_failure_keeps_valid_candidates(plan, monkeypatch):
    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 2)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(
        extract,
        "_detect_with_pdfplumber",
        lambda file_id, data, pages: (
            [_candidate(file_id, 0, "pdfplumber", "first")],
            ["pdfplumber page 2 failed"],
        ),
    )
    monkeypatch.setattr(
        extract,
        "_detect_with_text_grid_heuristic",
        lambda file_id, data, pages: (
            [_candidate(file_id, 1, "text_grid", "second")],
            [],
        ),
    )
    result = extract.detect_tables("file", b"synthetic", plan)
    assert result.status == "PARTIAL"
    assert [candidate.page_index for candidate in result.candidates] == [0, 1]
    assert result.errors == ["pdfplumber page 2 failed"]


def test_empty_document_has_no_table_and_no_ocr(plan, blank_pdf):
    engine = Engine(plan)
    ingested, _ = engine.ingest("blank.pdf", blank_pdf)
    result = engine.detect_tables(ingested.file_id, blank_pdf)
    assert result.status == "NO_TABLE"
    assert result.candidates == []
    assert plan.ocr.status == "DISABLED"


def test_scanned_image_document_has_no_table_without_ocr(plan, scanned_pdf):
    engine = Engine(plan)
    ingested, _ = engine.ingest("scan.pdf", scanned_pdf)
    result = engine.detect_tables(ingested.file_id, scanned_pdf)
    assert result.status == "NO_TABLE"
    assert result.candidates == []
    assert plan.ocr.status == "DISABLED"
