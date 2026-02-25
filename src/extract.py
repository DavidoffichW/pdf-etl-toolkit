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


def _has_pdfplumber() -> bool:
    try:
        import pdfplumber  # type: ignore
        return True
    except Exception:
        return False


def _has_fitz() -> bool:
    try:
        import fitz  # type: ignore
        return True
    except Exception:
        return False
    
# Public API

def detect_tables(
    file_id: str,
    data: bytes,
    run_plan: RunPlan,
) -> DetectionResult:

    if run_plan.tables.status != "OK":
        return DetectionResult(status="NO_TABLE", candidates=[])

    candidates: List[TableCandidate] = []

    if _has_pdfplumber():
        candidates = _detect_with_pdfplumber(file_id, data)
        if candidates:
            return DetectionResult(status="OK", candidates=candidates)

    if _has_fitz():
        candidates = _detect_with_pymupdf(file_id, data)
        if candidates:
            return DetectionResult(status="OK", candidates=candidates)

        candidates = _detect_with_text_grid_heuristic(file_id, data)
        if candidates:
            return DetectionResult(status="OK", candidates=candidates)

    return DetectionResult(status="NO_TABLE", candidates=[])


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


def _detect_with_text_grid_heuristic(file_id: str, data: bytes) -> List[TableCandidate]:
    import fitz  # type: ignore

    MIN_WORDS_PER_ROW = 3
    MIN_ROW_COUNT = 3
    ROW_Y_TOLERANCE = 4.0
    COL_X_TOLERANCE = 10.0

    candidates: List[TableCandidate] = []

    doc = fitz.open(stream=data, filetype="pdf")

    for page_index in range(len(doc)):
        page = doc[page_index]
        words = page.get_text("words")

        if not words:
            continue

        items: List[Tuple[float, float, float, float, str]] = []
        for w in words:
            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
            t = "" if txt is None else str(txt).strip()
            if not t:
                continue
            items.append((float(x0), float(y0), float(x1), float(y1), t))

        if not items:
            continue

        items.sort(key=lambda x: (x[1], x[0]))

        row_keys: List[float] = []
        row_items: Dict[int, List[Tuple[float, float, float, float, str]]] = {}

        for x0, y0, x1, y1, t in items:
            chosen = -1
            for i, ry in enumerate(row_keys):
                if abs(ry - y0) <= ROW_Y_TOLERANCE:
                    chosen = i
                    break
            if chosen < 0:
                row_keys.append(y0)
                row_items[len(row_keys) - 1] = [(x0, y0, x1, y1, t)]
            else:
                row_items[chosen].append((x0, y0, x1, y1, t))

        valid_row_indices: List[int] = []
        for ridx in range(len(row_keys)):
            if len(row_items.get(ridx, [])) >= MIN_WORDS_PER_ROW:
                valid_row_indices.append(ridx)

        if len(valid_row_indices) < MIN_ROW_COUNT:
            continue

        valid_row_indices.sort(key=lambda i: row_keys[i])

        col_anchors: List[float] = []
        for ridx in valid_row_indices:
            for x0, y0, x1, y1, t in row_items[ridx]:
                inserted = False
                for j, ax in enumerate(col_anchors):
                    if abs(ax - x0) <= COL_X_TOLERANCE:
                        inserted = True
                        break
                if not inserted:
                    col_anchors.append(x0)

        col_anchors.sort()

        if len(col_anchors) < 2:
            continue

        cells: List[TableCell] = []
        row_count = len(valid_row_indices)
        col_count = len(col_anchors)

        bbox_x0 = 1e18
        bbox_y0 = 1e18
        bbox_x1 = -1e18
        bbox_y1 = -1e18

        for out_r, ridx in enumerate(valid_row_indices):
            parts: Dict[int, List[Tuple[float, str]]] = {}
            row_words = list(row_items[ridx])
            row_words.sort(key=lambda x: x[0])

            for x0, y0, x1, y1, t in row_words:
                best_c = 0
                best_d = abs(col_anchors[0] - x0)
                for c, ax in enumerate(col_anchors[1:], start=1):
                    d = abs(ax - x0)
                    if d < best_d:
                        best_d = d
                        best_c = c

                if best_c not in parts:
                    parts[best_c] = []
                parts[best_c].append((x0, t))

                if x0 < bbox_x0:
                    bbox_x0 = x0
                if y0 < bbox_y0:
                    bbox_y0 = y0
                if x1 > bbox_x1:
                    bbox_x1 = x1
                if y1 > bbox_y1:
                    bbox_y1 = y1

            for out_c in range(col_count):
                segs = parts.get(out_c, [])
                if not segs:
                    text = ""
                else:
                    segs.sort(key=lambda z: z[0])
                    text = " ".join(s for _, s in segs).strip()
                cells.append(TableCell(row=out_r, col=out_c, text=text))

        bbox = (float(bbox_x0), float(bbox_y0), float(bbox_x1), float(bbox_y1))
        score = _score_table(row_count, col_count, bbox)

        candidate_id = stable_id(
            "cand",
            file_id,
            str(page_index),
            "heuristic",
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

    doc.close()
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