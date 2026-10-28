from __future__ import annotations

import csv
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple

from utils import canonical_json_bytes, normalize_headers


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FIXED_DOCUMENT_TIME = datetime(1980, 1, 1, tzinfo=timezone.utc)
_DANGEROUS_PREFIX = re.compile(r"^[\x00-\x20]*([=+\-@])")
_NEGATIVE_NUMBER = re.compile(r"^-(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


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


def escape_spreadsheet_value(value: Any) -> str:
    """Escape formula-like text for CSV and XLSX without changing source state."""
    text = "" if value is None else str(value)
    match = _DANGEROUS_PREFIX.match(text)
    if not match:
        return text
    candidate = text.lstrip("\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f"
                            "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f ")
    if match.group(1) == "-" and _NEGATIVE_NUMBER.fullmatch(candidate):
        return text
    return "'" + text


def build_results_csv_bytes(table: ExportTable) -> bytes:
    headers = ["file_id", "page_index", "candidate_id", "row_index"] + list(
        table.schema_headers
    )
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in table.rows:
        writer.writerow(
            [
                row.file_id,
                str(int(row.page_index)),
                row.candidate_id,
                str(int(row.row_index)),
                *[escape_spreadsheet_value(value) for value in row.values],
            ]
        )
    return buffer.getvalue().encode("utf-8")


def build_results_jsonl_bytes(table: ExportTable) -> bytes:
    output = BytesIO()
    headers = list(table.schema_headers)
    for row in table.rows:
        row_object: Dict[str, Any] = {
            "file_id": row.file_id,
            "page_index": int(row.page_index),
            "candidate_id": row.candidate_id,
            "row_index": int(row.row_index),
            "row": {
                headers[index]: (row.values[index] if row.values[index] is not None else "")
                for index in range(len(headers))
            },
        }
        output.write(
            json.dumps(
                row_object,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        output.write(b"\n")
    return output.getvalue()


def build_events_jsonl_bytes(events: List[Dict[str, Any]]) -> bytes:
    """Export reproducible event facts while leaving runtime timestamps in memory."""
    output = BytesIO()
    for event in events:
        export_event = {key: value for key, value in event.items() if key != "timestamp"}
        output.write(
            json.dumps(
                export_event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        output.write(b"\n")
    return output.getvalue()


def build_manifest_json_bytes(manifest: Dict[str, Any]) -> bytes:
    return canonical_json_bytes(manifest)


def maybe_build_xlsx_bytes(table: ExportTable) -> Optional[bytes]:
    try:
        from openpyxl import Workbook  # type: ignore
    except Exception:
        return None

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "results"
    workbook.properties.creator = "pdf-etl-toolkit"
    workbook.properties.lastModifiedBy = "pdf-etl-toolkit"
    workbook.properties.created = FIXED_DOCUMENT_TIME
    workbook.properties.modified = FIXED_DOCUMENT_TIME

    worksheet.append(
        ["file_id", "page_index", "candidate_id", "row_index", *table.schema_headers]
    )
    for row in table.rows:
        worksheet.append(
            [
                row.file_id,
                int(row.page_index),
                row.candidate_id,
                int(row.row_index),
                *[escape_spreadsheet_value(value) for value in row.values],
            ]
        )

    raw = BytesIO()
    workbook.save(raw)
    workbook.close()
    return _normalize_zip(raw.getvalue())


def _normalize_zip(data: bytes) -> bytes:
    with zipfile.ZipFile(BytesIO(data)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    core_name = "docProps/core.xml"
    if core_name in members:
        members[core_name], replacements = re.subn(
            rb"(<dcterms:modified\b[^>]*>)[^<]*(</dcterms:modified>)",
            rb"\g<1>1980-01-01T00:00:00Z\g<2>",
            members[core_name],
            count=1,
        )
        if replacements != 1:
            raise ValueError("XLSX core properties contain no unique modified timestamp")
    return _build_zip(members)


def _build_zip(members: Dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe ZIP member name: {name}")
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                members[name],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def build_export_zip(
    *,
    table_headers: Sequence[str],
    table_rows: Sequence[Tuple[str, int, str, int, Sequence[str]]],
    manifest: Dict[str, Any],
    events: List[Dict[str, Any]],
    include_xlsx: bool,
    extra_members: Optional[Dict[str, bytes]] = None,
) -> bytes:
    normalized_headers = normalize_headers(list(table_headers))
    rows = [
        ExportRow(
            file_id=str(file_id),
            page_index=int(page_index),
            candidate_id=str(candidate_id),
            row_index=int(row_index),
            values=["" if value is None else str(value) for value in values],
        )
        for file_id, page_index, candidate_id, row_index, values in table_rows
    ]
    table = ExportTable(normalized_headers, rows)
    members = {
        "events.jsonl": build_events_jsonl_bytes(events),
        "manifest.json": build_manifest_json_bytes(manifest),
        "results.csv": build_results_csv_bytes(table),
        "results.jsonl": build_results_jsonl_bytes(table),
    }
    if include_xlsx:
        xlsx = maybe_build_xlsx_bytes(table)
        if xlsx is not None:
            members["results.xlsx"] = xlsx
    if extra_members:
        members.update(extra_members)
    return _build_zip(members)
