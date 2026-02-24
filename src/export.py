from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

from utils import canonical_json_bytes, normalize_headers


@dataclass(frozen=True)
class ExportRow:
    file_id: str
    page_index: int
    candidate_id: str
    row_index: int
    values: List[str]


@dataclass(frozen=True)
class ExportTable:
    schema_headers: List[str]
    rows: List[ExportRow]


def build_results_csv_bytes(table: ExportTable) -> bytes:
    headers = ["file_id", "page_index", "candidate_id", "row_index"] + list(table.schema_headers)

    buf = StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)

    for r in table.rows:
        writer.writerow(
            [
                r.file_id,
                str(int(r.page_index)),
                r.candidate_id,
                str(int(r.row_index)),
                *[v if v is not None else "" for v in r.values],
            ]
        )

    return buf.getvalue().encode("utf-8")


def build_results_jsonl_bytes(table: ExportTable) -> bytes:
    out = BytesIO()
    headers = list(table.schema_headers)

    for r in table.rows:
        row_obj: Dict[str, Any] = {
            "file_id": r.file_id,
            "page_index": int(r.page_index),
            "candidate_id": r.candidate_id,
            "row_index": int(r.row_index),
            "row": {headers[i]: (r.values[i] if r.values[i] is not None else "") for i in range(len(headers))},
        }
        line = json.dumps(row_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        out.write(line)
        out.write(b"\n")

    return out.getvalue()


def build_events_jsonl_bytes(events: List[Dict[str, Any]]) -> bytes:
    out = BytesIO()
    for ev in events:
        line = json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        out.write(line)
        out.write(b"\n")
    return out.getvalue()


def build_manifest_json_bytes(manifest: Dict[str, Any]) -> bytes:
    return canonical_json_bytes(manifest)


def maybe_build_xlsx_bytes(table: ExportTable) -> Optional[bytes]:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None

    data_rows: List[Dict[str, Any]] = []
    headers = list(table.schema_headers)

    for r in table.rows:
        row_obj: Dict[str, Any] = {
            "file_id": r.file_id,
            "page_index": int(r.page_index),
            "candidate_id": r.candidate_id,
            "row_index": int(r.row_index),
        }
        for i, h in enumerate(headers):
            row_obj[h] = r.values[i] if r.values[i] is not None else ""
        data_rows.append(row_obj)

    df = pd.DataFrame(data_rows)

    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="results", index=False)
    return out.getvalue()


def build_export_zip(
    *,
    table_headers: Sequence[str],
    table_rows: Sequence[Tuple[str, int, str, int, Sequence[str]]],
    manifest: Dict[str, Any],
    events: List[Dict[str, Any]],
    include_xlsx: bool,
) -> bytes:
    """
    table_headers:
        Column names for the sliced table. These will be normalized deterministically.

    table_rows:
        Each row is:
            (file_id, page_index, candidate_id, row_index, values[])
        values[] must match length of normalized headers.

    include_xlsx:
        If True and pandas is available, results.xlsx is included.
    """
    norm_headers = normalize_headers(list(table_headers))

    export_rows: List[ExportRow] = []
    for file_id, page_index, candidate_id, row_index, values in table_rows:
        export_rows.append(
            ExportRow(
                file_id=str(file_id),
                page_index=int(page_index),
                candidate_id=str(candidate_id),
                row_index=int(row_index),
                values=[("" if v is None else str(v)) for v in list(values)],
            )
        )

    table = ExportTable(schema_headers=norm_headers, rows=export_rows)

    results_csv = build_results_csv_bytes(table)
    results_jsonl = build_results_jsonl_bytes(table)
    manifest_json = build_manifest_json_bytes(manifest)
    events_jsonl = build_events_jsonl_bytes(events)

    xlsx_bytes: Optional[bytes] = None
    if include_xlsx:
        xlsx_bytes = maybe_build_xlsx_bytes(table)

    zbuf = BytesIO()
    with zipfile.ZipFile(zbuf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("results.csv", results_csv)
        z.writestr("results.jsonl", results_jsonl)
        z.writestr("manifest.json", manifest_json)
        z.writestr("events.jsonl", events_jsonl)
        if xlsx_bytes is not None:
            z.writestr("results.xlsx", xlsx_bytes)

    return zbuf.getvalue()