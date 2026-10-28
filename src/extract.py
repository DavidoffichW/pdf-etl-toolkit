from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runplan import RunPlan
from utils import stable_id


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
    provider: str = "unknown"


@dataclass(frozen=True)
class DetectionResult:
    status: str
    candidates: List[TableCandidate]
    errors: List[str] = field(default_factory=list)


def _has_pdfplumber() -> bool:
    try:
        import pdfplumber  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _page_count(data: bytes, run_plan: RunPlan) -> int:
    from pypdf import PdfReader  # type: ignore

    return len(PdfReader(BytesIO(data)).pages)


def detect_tables(file_id: str, data: bytes, run_plan: RunPlan) -> DetectionResult:
    """Apply the provider cascade independently to every page."""
    if run_plan.tables.status != "OK":
        return DetectionResult(status="NO_TABLE", candidates=[])

    remaining = set(range(_page_count(data, run_plan)))
    candidates: List[TableCandidate] = []
    errors: List[str] = []
    providers = []
    if _has_pdfplumber():
        providers.extend(
            [
                ("pdfplumber", _detect_with_pdfplumber),
                ("text_grid", _detect_with_text_grid_heuristic),
            ]
        )

    attempted = False
    for provider_name, provider in providers:
        if not remaining:
            break
        attempted = True
        try:
            found, provider_errors = provider(file_id, data, sorted(remaining))
        except Exception as exc:
            errors.append(f"{provider_name} initialization failed: {exc}")
            continue
        errors.extend(provider_errors)
        candidates.extend(found)
        remaining.difference_update({candidate.page_index for candidate in found})

    candidates.sort(
        key=lambda candidate: (
            int(candidate.page_index),
            float(candidate.bbox[1]),
            float(candidate.bbox[0]),
            -float(candidate.score),
            candidate.candidate_id,
        )
    )
    if candidates:
        return DetectionResult("PARTIAL" if errors else "OK", candidates, errors)
    if attempted and errors:
        return DetectionResult("FAILED", [], errors)
    return DetectionResult("NO_TABLE", [], [])


def _detect_with_pdfplumber(
    file_id: str,
    data: bytes,
    page_indices: Sequence[int],
) -> Tuple[List[TableCandidate], List[str]]:
    import pdfplumber  # type: ignore

    candidates: List[TableCandidate] = []
    errors: List[str] = []
    with pdfplumber.open(BytesIO(data)) as pdf:
        for page_index in page_indices:
            if page_index >= len(pdf.pages):
                errors.append(f"pdfplumber page {page_index + 1} is unavailable")
                continue
            try:
                tables = pdf.pages[page_index].find_tables()
            except Exception as exc:
                errors.append(f"pdfplumber page {page_index + 1} failed: {exc}")
                continue
            for table_index, table in enumerate(tables or []):
                try:
                    candidate = _candidate_from_rows(
                        file_id=file_id,
                        page_index=page_index,
                        table_index=table_index,
                        provider="pdfplumber",
                        bbox=tuple(float(value) for value in table.bbox),
                        raw=table.extract(),
                    )
                except Exception as exc:
                    errors.append(
                        f"pdfplumber page {page_index + 1} table {table_index + 1} failed: {exc}"
                    )
                    continue
                if candidate is not None:
                    candidates.append(candidate)
    return candidates, errors


def _candidate_from_rows(
    *,
    file_id: str,
    page_index: int,
    table_index: int,
    provider: str,
    bbox: Tuple[float, float, float, float],
    raw: Optional[Sequence[Sequence[Any]]],
) -> Optional[TableCandidate]:
    if not raw:
        return None
    row_count = len(raw)
    col_count = max((len(row) for row in raw), default=0)
    if row_count <= 0 or col_count <= 0:
        return None
    cells: List[TableCell] = []
    for row_index, row in enumerate(raw):
        for col_index in range(col_count):
            value = row[col_index] if col_index < len(row) else ""
            cells.append(
                TableCell(
                    row=row_index,
                    col=col_index,
                    text="" if value is None else str(value).strip(),
                )
            )
    return TableCandidate(
        candidate_id=stable_id("cand", file_id, str(page_index), provider, str(table_index)),
        file_id=file_id,
        page_index=page_index,
        bbox=bbox,
        row_count=row_count,
        col_count=col_count,
        score=_score_table(row_count, col_count, bbox),
        cells=cells,
        provider=provider,
    )


def _detect_with_text_grid_heuristic(
    file_id: str,
    data: bytes,
    page_indices: Sequence[int],
) -> Tuple[List[TableCandidate], List[str]]:
    import pdfplumber  # type: ignore

    candidates: List[TableCandidate] = []
    errors: List[str] = []
    with pdfplumber.open(BytesIO(data)) as document:
        for page_index in page_indices:
            if page_index >= len(document.pages):
                errors.append(f"text_grid page {page_index + 1} is unavailable")
                continue
            try:
                words = document.pages[page_index].extract_words(
                    x_tolerance=1,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=False,
                )
                candidate = _heuristic_candidate(file_id, page_index, words)
            except Exception as exc:
                errors.append(f"text_grid page {page_index + 1} failed: {exc}")
                continue
            if candidate is not None:
                candidates.append(candidate)
    return candidates, errors


def _heuristic_candidate(
    file_id: str,
    page_index: int,
    words: Sequence[Dict[str, Any]],
) -> Optional[TableCandidate]:
    items = [
        (
            float(word["x0"]),
            float(word["top"]),
            float(word["x1"]),
            float(word["bottom"]),
            str(word["text"]).strip(),
        )
        for word in words
        if word.get("text") is not None and str(word["text"]).strip()
    ]
    if not items:
        return None
    items.sort(key=lambda item: (item[1], item[0]))

    row_keys: List[float] = []
    row_items: Dict[int, List[Tuple[float, float, float, float, str]]] = {}
    for item in items:
        chosen = next(
            (index for index, row_y in enumerate(row_keys) if abs(row_y - item[1]) <= 4.0),
            None,
        )
        if chosen is None:
            chosen = len(row_keys)
            row_keys.append(item[1])
            row_items[chosen] = []
        row_items[chosen].append(item)

    valid_rows = [index for index in range(len(row_keys)) if len(row_items[index]) >= 3]
    if len(valid_rows) < 3:
        return None
    valid_rows.sort(key=lambda index: row_keys[index])

    column_anchors: List[float] = []
    for row_index in valid_rows:
        for item in row_items[row_index]:
            if not any(abs(anchor - item[0]) <= 10.0 for anchor in column_anchors):
                column_anchors.append(item[0])
    column_anchors.sort()
    if len(column_anchors) < 2:
        return None

    cells: List[TableCell] = []
    for output_row, row_index in enumerate(valid_rows):
        parts: Dict[int, List[Tuple[float, str]]] = {}
        for item in sorted(row_items[row_index], key=lambda value: value[0]):
            output_col = min(
                range(len(column_anchors)),
                key=lambda index: abs(column_anchors[index] - item[0]),
            )
            parts.setdefault(output_col, []).append((item[0], item[4]))
        for output_col in range(len(column_anchors)):
            segments = sorted(parts.get(output_col, []), key=lambda value: value[0])
            cells.append(
                TableCell(
                    row=output_row,
                    col=output_col,
                    text=" ".join(text for _, text in segments).strip(),
                )
            )

    bbox = (
        min(item[0] for index in valid_rows for item in row_items[index]),
        min(item[1] for index in valid_rows for item in row_items[index]),
        max(item[2] for index in valid_rows for item in row_items[index]),
        max(item[3] for index in valid_rows for item in row_items[index]),
    )
    return TableCandidate(
        candidate_id=stable_id("cand", file_id, str(page_index), "text_grid", "0"),
        file_id=file_id,
        page_index=page_index,
        bbox=bbox,
        row_count=len(valid_rows),
        col_count=len(column_anchors),
        score=_score_table(len(valid_rows), len(column_anchors), bbox),
        cells=cells,
        provider="text_grid",
    )


def _score_table(
    row_count: int,
    col_count: int,
    bbox: Tuple[float, float, float, float],
) -> float:
    width = abs(bbox[2] - bbox[0])
    height = abs(bbox[3] - bbox[1])
    return float((row_count * col_count * 0.6) + (width * height * 0.4))
