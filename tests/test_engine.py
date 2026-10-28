from __future__ import annotations

from io import BytesIO

import fitz
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
        calls.append(("pymupdf", tuple(pages)))
        return [_candidate(file_id, 1, "pymupdf", "second")], []

    def heuristic(file_id, data, pages):
        calls.append(("text_grid", tuple(pages)))
        return [], []

    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 2)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(extract, "_has_fitz", lambda: True)
    monkeypatch.setattr(extract, "_detect_with_pdfplumber", preferred)
    monkeypatch.setattr(extract, "_detect_with_pymupdf", fallback)
    monkeypatch.setattr(extract, "_detect_with_text_grid_heuristic", heuristic)

    result = extract.detect_tables("file", b"synthetic", plan)
    assert result.status == "OK"
    assert [(item.page_index, item.provider) for item in result.candidates] == [
        (0, "pdfplumber"),
        (1, "pymupdf"),
    ]
    assert calls == [("pdfplumber", (0, 1)), ("pymupdf", (1,))]


def test_provider_initialization_failure_falls_back(plan, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 1)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(extract, "_has_fitz", lambda: True)
    monkeypatch.setattr(extract, "_detect_with_pdfplumber", failed)
    monkeypatch.setattr(
        extract,
        "_detect_with_pymupdf",
        lambda file_id, data, pages: ([_candidate(file_id, 0, "pymupdf", "ok")], []),
    )

    result = extract.detect_tables("file", b"synthetic", plan)
    assert result.status == "PARTIAL"
    assert result.candidates[0].provider == "pymupdf"
    assert "pdfplumber initialization failed" in result.errors[0]


def test_detection_distinguishes_failure_from_no_table(plan, monkeypatch):
    monkeypatch.setattr(extract, "_page_count", lambda data, run_plan: 1)
    monkeypatch.setattr(extract, "_has_pdfplumber", lambda: True)
    monkeypatch.setattr(extract, "_has_fitz", lambda: False)
    monkeypatch.setattr(
        extract,
        "_detect_with_pdfplumber",
        lambda file_id, data, pages: ([], ["page failed"]),
    )
    assert extract.detect_tables("file", b"synthetic", plan).status == "FAILED"

    monkeypatch.setattr(extract, "_detect_with_pdfplumber", lambda file_id, data, pages: ([], []))
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
    assert all(candidate.provider in {"pdfplumber", "pymupdf", "text_grid"} for candidate in first.candidates)


def test_fitz_metadata_document_is_closed(plan, monkeypatch):
    closed = {"value": False}

    class Rect:
        width = 10
        height = 20

    class Page:
        rect = Rect()

    class Document:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed["value"] = True

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return Page()

    monkeypatch.setattr(fitz, "open", lambda **kwargs: Document())
    ingested, pages = Engine(plan).ingest("synthetic.pdf", b"synthetic")
    assert ingested.page_count == 1
    assert len(pages) == 1
    assert closed["value"] is True
