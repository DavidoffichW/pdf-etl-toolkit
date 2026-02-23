from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple
from io import BytesIO

from utils import stable_id, canonical_sort_key_pair_int
from runplan import RunPlan


@dataclass(frozen=True)
class TableCell:
    row: int
    col: int
    text: str


@dataclass(frozen=True)
class TableCandidate:
    candidate_id: str
    file_id: str
    page_index: int
    bbox: Tuple[float, float, float, float]
    row_count: int
    col_count: int
    score: float
    cells: List[TableCell]


@dataclass(frozen=True)
class DetectionResult:
    status: str
    candidates: List[TableCandidate]



# Public API



def detect_tables(
    file_id: str,
    data: bytes,
    run_plan: RunPlan,
) -> DetectionResult:

    if run_plan.tables.status != "OK":
        return DetectionResult(status="NO_TABLE", candidates=[])

    provider = run_plan.tables.provider

    if provider == "pymupdf_tables":
        candidates = _detect_with_pymupdf(file_id, data)
    elif provider == "pdfplumber":
        candidates = _detect_with_pdfplumber(file_id, data)
    else:
        candidates = []

    if not candidates:
        return DetectionResult(status="NO_TABLE", candidates=[])

    # Deterministic sorting by score descending then bbox top-left
    candidates = sorted(
        candidates,
        key=lambda c: (-c.score, c.page_index, c.bbox[1], c.bbox[0]),
    )

    if len(candidates) == 1:
        return DetectionResult(status="OK", candidates=candidates)

    # If multiple candidates exist, surface ambiguity
    top_score = candidates[0].score
    second_score = candidates[1].score

    if abs(top_score - second_score) < 0.01:
        return DetectionResult(status="AMBIGUOUS", candidates=candidates)

    return DetectionResult(status="OK", candidates=candidates)



# PyMuPDF Detection



def _detect_with_pymupdf(file_id: str, data: bytes) -> List[TableCandidate]:
    import fitz  # type: ignore

    doc = fitz.open(stream=data, filetype="pdf")
    candidates: List[TableCandidate] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        try:
            tables = page.find_tables()
        except Exception:
            continue

        if not tables or not tables.tables:
            continue

        for t_index, table in enumerate(tables.tables):
            bbox = tuple(table.bbox)
            raw = table.extract()

            if not raw:
                continue

            cells: List[TableCell] = []
            row_count = len(raw)
            col_count = max(len(r) for r in raw)

            for r_idx, row in enumerate(raw):
                for c_idx, value in enumerate(row):
                    text = "" if value is None else str(value).strip()
                    cells.append(TableCell(row=r_idx, col=c_idx, text=text))

            score = _score_table(row_count, col_count, bbox)

            candidate_id = stable_id(
                "cand",
                file_id,
                str(page_index),
                str(t_index),
            )

            candidates.append(
                TableCandidate(
                    candidate_id=candidate_id,
                    file_id=file_id,
                    page_index=page_index,
                    bbox=bbox,
                    row_count=row_count,
                    col_count=col_count,
                    score=score,
                    cells=cells,
                )
            )

    return candidates



# pdfplumber Detection



def _detect_with_pdfplumber(file_id: str, data: bytes) -> List[TableCandidate]:
    import pdfplumber  # type: ignore

    candidates: List[TableCandidate] = []

    with pdfplumber.open(BytesIO(data)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            try:
                tables = page.find_tables()
            except Exception:
                continue

            if not tables:
                continue

            for t_index, table in enumerate(tables):
                raw = table.extract()

                if not raw:
                    continue

                bbox = table.bbox
                cells: List[TableCell] = []
                row_count = len(raw)
                col_count = max(len(r) for r in raw)

                for r_idx, row in enumerate(raw):
                    for c_idx, value in enumerate(row):
                        text = "" if value is None else str(value).strip()
                        cells.append(TableCell(row=r_idx, col=c_idx, text=text))

                score = _score_table(row_count, col_count, bbox)

                candidate_id = stable_id(
                    "cand",
                    file_id,
                    str(page_index),
                    str(t_index),
                )

                candidates.append(
                    TableCandidate(
                        candidate_id=candidate_id,
                        file_id=file_id,
                        page_index=page_index,
                        bbox=bbox,
                        row_count=row_count,
                        col_count=col_count,
                        score=score,
                        cells=cells,
                    )
                )

    return candidates



# Scoring



def _score_table(
    row_count: int,
    col_count: int,
    bbox: Tuple[float, float, float, float],
) -> float:
    width = abs(bbox[2] - bbox[0])
    height = abs(bbox[3] - bbox[1])
    area = width * height

    size_factor = row_count * col_count
    score = (size_factor * 0.6) + (area * 0.4)

    return float(score)