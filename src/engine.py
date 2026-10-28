from __future__ import annotations

from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
import stat
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from runplan import RunPlan
from utils import canonical_json_bytes, sha256_bytes, stable_id, utc_now_iso

import extract
import export as export_mod


@dataclass(frozen=True)
class IngestedFile:
    file_id: str
    filename: str
    size_bytes: int
    sha256: str
    page_count: int


@dataclass(frozen=True)
class PageInfo:
    file_id: str
    page_index: int
    width: float
    height: float


@dataclass(frozen=True)
class Event:
    timestamp: str
    level: str
    message: str


@dataclass(frozen=True)
class BatchLimits:
    max_file_bytes: int = 50 * 1024 * 1024
    max_total_bytes: int = 250 * 1024 * 1024
    max_files: int = 100
    max_pages: int = 2_000


@dataclass(frozen=True)
class BatchFileResult:
    filename: str
    status: str
    message: str
    size_bytes: int
    page_count: int


@dataclass(frozen=True)
class BatchExtractionResult:
    data: bytes
    report: bytes
    files: List[BatchFileResult]
    bytes_read: int
    pages_processed: int

    @property
    def success_count(self) -> int:
        return sum(item.status == "OK" for item in self.files)

    @property
    def failure_count(self) -> int:
        return sum(item.status != "OK" for item in self.files)


class Engine:
    """
    Pure orchestration layer.
    No Streamlit imports allowed.
    No filesystem writes.
    """

    def __init__(self, run_plan: RunPlan) -> None:
        self.run_plan = run_plan
        self._events: List[Event] = []

    def _log(self, level: str, message: str) -> None:
        self._events.append(
            Event(
                timestamp=utc_now_iso(),
                level=level,
                message=message,
            )
        )

    def get_events(self) -> List[Dict[str, Any]]:
        return [asdict(e) for e in self._events]

    def ingest(self, filename: str, data: bytes) -> Tuple[IngestedFile, List[PageInfo]]:
        file_hash = sha256_bytes(data)
        file_id = stable_id("file", file_hash)

        self._log("INFO", f"Ingesting file: {filename}")
        self._log("INFO", f"Computed sha256: {file_hash}")

        page_count, page_infos = self._extract_page_metadata(file_id, data)

        ingested = IngestedFile(
            file_id=file_id,
            filename=filename,
            size_bytes=len(data),
            sha256=file_hash,
            page_count=page_count,
        )

        self._log("INFO", f"Page count detected: {page_count}")

        return ingested, page_infos

    def _extract_page_metadata(self, file_id: str, data: bytes) -> Tuple[int, List[PageInfo]]:
        provider = self.run_plan.pdf.provider

        if provider == "fitz":
            import fitz  # type: ignore

            page_infos: List[PageInfo] = []
            with fitz.open(stream=data, filetype="pdf") as document:
                for i in range(len(document)):
                    page = document[i]
                    rect = page.rect
                    page_infos.append(
                        PageInfo(
                            file_id=file_id,
                            page_index=i,
                            width=float(rect.width),
                            height=float(rect.height),
                        )
                    )
                return len(document), page_infos

        if provider == "pypdf":
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(data))
            page_infos = []
            for i, page in enumerate(reader.pages):
                try:
                    width = float(page.mediabox.width)
                    height = float(page.mediabox.height)
                except Exception:
                    width = 0.0
                    height = 0.0
                page_infos.append(
                    PageInfo(
                        file_id=file_id,
                        page_index=i,
                        width=width,
                        height=height,
                    )
                )
            return len(reader.pages), page_infos

        raise RuntimeError("No valid PDF provider configured in RunPlan.")

    def build_manifest(self, ingested_files: List[IngestedFile]) -> Dict[str, Any]:
        manifest = {
            "run_plan": {
                "pdf": {
                    "provider": self.run_plan.pdf.provider,
                    "status": self.run_plan.pdf.status,
                    "reason": self.run_plan.pdf.reason,
                },
                "tables": {
                    "provider": self.run_plan.tables.provider,
                    "status": self.run_plan.tables.status,
                    "reason": self.run_plan.tables.reason,
                },
                "ocr": {
                    "provider": self.run_plan.ocr.provider,
                    "status": self.run_plan.ocr.status,
                    "reason": self.run_plan.ocr.reason,
                },
                "export": {
                    "provider": self.run_plan.export.provider,
                    "status": self.run_plan.export.status,
                    "reason": self.run_plan.export.reason,
                },
            },
            "files": [
                {
                    "file_id": f.file_id,
                    "filename": f.filename,
                    "size_bytes": f.size_bytes,
                    "sha256": f.sha256,
                    "page_count": f.page_count,
                }
                for f in ingested_files
            ],
        }
        return manifest

    def manifest_bytes(self, manifest: Dict[str, Any]) -> bytes:
        return canonical_json_bytes(manifest)

    def ingested_from_docs_meta(self, docs_meta: Sequence[Dict[str, Any]]) -> List[IngestedFile]:
        out: List[IngestedFile] = []
        for d in docs_meta:
            out.append(
                IngestedFile(
                    file_id=str(d.get("doc_id") or d.get("file_id")),
                    filename=str(d.get("filename", "")),
                    size_bytes=int(d.get("size_bytes", 0)),
                    sha256=str(d.get("sha256", "")),
                    page_count=int(d.get("page_count", 0)),
                )
            )
        return out

    def detect_tables(self, file_id: str, data: bytes) -> extract.DetectionResult:
        if self.run_plan.tables.status != "OK":
            self._log("WARN", f"Table detection disabled: {self.run_plan.tables.reason}")
            return extract.DetectionResult(status="NO_TABLE", candidates=[])

        res = extract.detect_tables(file_id=file_id, data=data, run_plan=self.run_plan)
        self._log("INFO", f"detect_tables status={res.status} candidates={len(res.candidates)}")
        for message in res.errors:
            self._log("WARN", message)
        return res

    def candidate_to_grid(self, cand: extract.TableCandidate) -> List[List[str]]:
        rows = int(cand.row_count)
        cols = int(cand.col_count)
        if rows <= 0 or cols <= 0:
            return []
        grid: List[List[str]] = [["" for _ in range(cols)] for _ in range(rows)]
        for cell in cand.cells:
            r = int(cell.row)
            c = int(cell.col)
            if 0 <= r < rows and 0 <= c < cols:
                grid[r][c] = "" if cell.text is None else str(cell.text)
        return grid

    def slice_grid(
        self,
        grid: List[List[str]],
        *,
        mode: str,
        row_1b: Optional[int],
        col_1b: Optional[int],
    ) -> Tuple[List[str], List[List[str]]]:
        if not grid:
            return [], []

        rcount = len(grid)
        ccount = len(grid[0]) if rcount else 0

        if mode == "table":
            headers = [f"col_{i+1}" for i in range(ccount)]
            return headers, [list(r) for r in grid]

        if mode == "row":
            if row_1b is None:
                raise ValueError("row is required for row slice mode")
            r = int(row_1b) - 1
            if r < 0 or r >= rcount:
                raise ValueError("row index out of range")
            headers = [f"col_{i+1}" for i in range(ccount)]
            return headers, [list(grid[r])]

        if mode == "column":
            if col_1b is None:
                raise ValueError("column is required for column slice mode")
            c = int(col_1b) - 1
            if c < 0 or c >= ccount:
                raise ValueError("column index out of range")
            headers = ["col_1"]
            out_rows = [[grid[r][c]] for r in range(rcount)]
            return headers, out_rows

        if mode == "cell":
            if row_1b is None or col_1b is None:
                raise ValueError("row and column are required for cell slice mode")
            r = int(row_1b) - 1
            c = int(col_1b) - 1
            if r < 0 or r >= rcount:
                raise ValueError("row index out of range")
            if c < 0 or c >= ccount:
                raise ValueError("column index out of range")
            headers = ["col_1"]
            return headers, [[grid[r][c]]]

        raise ValueError("invalid slice mode")

    def _build_csv_bytes(
        self,
        *,
        table_headers: Sequence[str],
        table_rows: Sequence[Tuple[str, int, str, int, Sequence[str]]],
    ) -> bytes:
        norm_headers = export_mod.normalize_headers(list(table_headers))
        export_rows: List[export_mod.ExportRow] = []
        for file_id, page_index, candidate_id, row_index, values in table_rows:
            export_rows.append(
                export_mod.ExportRow(
                    file_id=str(file_id),
                    page_index=int(page_index),
                    candidate_id=str(candidate_id),
                    row_index=int(row_index),
                    values=[("" if v is None else str(v)) for v in list(values)],
                )
            )
        table = export_mod.ExportTable(schema_headers=list(norm_headers), rows=export_rows)
        return export_mod.build_results_csv_bytes(table)

    def export_interactive(
        self,
        *,
        file_id: str,
        candidates: Sequence[extract.TableCandidate],
        selected_candidate_indices: Sequence[int],
        slice_configs: Dict[int, Dict[str, Any]],
        docs_meta: Sequence[Dict[str, Any]],
        export_format: str,
        include_xlsx: bool,
    ) -> bytes:
        event_start = len(self._events)
        indices = sorted(
            {
                int(index)
                for index in selected_candidate_indices
                if 0 <= int(index) < len(candidates)
            }
        )
        if not indices:
            self._log("WARN", "No valid candidate indices selected.")

        out_headers: Optional[List[str]] = None
        out_rows: List[Tuple[str, int, str, int, Sequence[str]]] = []
        for index in indices:
            candidate = candidates[index]
            config = slice_configs.get(index, {})
            try:
                headers, sliced = self.slice_grid(
                    self.candidate_to_grid(candidate),
                    mode=str(config.get("mode", "table")),
                    row_1b=(None if config.get("row") in (None, "") else int(config["row"])),
                    col_1b=(
                        None
                        if config.get("column") in (None, "")
                        else int(config["column"])
                    ),
                )
            except Exception as exc:
                self._log("WARN", f"Slice failed for candidate idx={index}: {exc}")
                continue
            if out_headers is not None and list(headers) != out_headers:
                self._log("WARN", f"Schema mismatch for candidate idx={index}; skipping.")
                continue
            out_headers = list(headers)
            for row_index, values in enumerate(sliced):
                out_rows.append(
                    (
                        candidate.file_id,
                        int(candidate.page_index),
                        candidate.candidate_id,
                        row_index,
                        list(values),
                    )
                )

        if out_headers is None:
            out_headers = []
        if export_format == "csv":
            return self._build_csv_bytes(table_headers=out_headers, table_rows=out_rows)
        if export_format != "zip":
            raise ValueError("export format must be 'csv' or 'zip'")
        return export_mod.build_export_zip(
            table_headers=out_headers,
            table_rows=out_rows,
            manifest=self.build_manifest(self.ingested_from_docs_meta(docs_meta)),
            events=self.get_events()[event_start:],
            include_xlsx=bool(include_xlsx),
        )

    def batch_extract_directory(
        self,
        *,
        directory_path: str,
        page_1b: int,
        table_index_1b: int,
        slice_mode: str,
        row_1b: Optional[int],
        col_1b: Optional[int],
        export_format: str,
        include_xlsx: bool,
        limits: Optional[BatchLimits] = None,
    ) -> bytes:
        return self.batch_extract_directory_result(
            directory_path=directory_path,
            page_1b=page_1b,
            table_index_1b=table_index_1b,
            slice_mode=slice_mode,
            row_1b=row_1b,
            col_1b=col_1b,
            export_format=export_format,
            include_xlsx=include_xlsx,
            limits=limits,
        ).data

    def batch_extract_directory_result(
        self,
        *,
        directory_path: str,
        page_1b: int,
        table_index_1b: int,
        slice_mode: str,
        row_1b: Optional[int],
        col_1b: Optional[int],
        export_format: str,
        include_xlsx: bool,
        limits: Optional[BatchLimits] = None,
    ) -> BatchExtractionResult:
        limits = limits or BatchLimits()
        event_start = len(self._events)
        page_index = int(page_1b) - 1
        if page_index < 0:
            raise ValueError("page must be >= 1")
        table_index = int(table_index_1b) - 1
        if table_index < 0:
            raise ValueError("table index must be >= 1")
        if export_format not in {"csv", "zip"}:
            raise ValueError("export format must be 'csv' or 'zip'")

        root = Path(directory_path).expanduser()
        try:
            root_stat = root.lstat()
            root_resolved = root.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"Batch directory is inaccessible: {exc}") from exc
        if root.is_symlink() or self._is_reparse_point(root_stat):
            raise ValueError("Batch directory must not be a symlink or reparse point")
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError("Batch path is not a directory")

        try:
            paths = sorted(
                [path for path in root.iterdir() if path.suffix.lower() == ".pdf"],
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as exc:
            raise ValueError(f"Batch directory cannot be listed: {exc}") from exc
        if not paths:
            raise ValueError("No PDF files found in directory")
        if len(paths) > limits.max_files:
            raise ValueError(
                f"Batch has {len(paths)} PDF entries; limit is {limits.max_files}"
            )

        files: List[Tuple[Path, int]] = []
        file_results: List[BatchFileResult] = []
        for path in paths:
            try:
                file_stat = path.lstat()
                resolved = path.resolve(strict=True)
                if path.is_symlink() or self._is_reparse_point(file_stat):
                    raise ValueError("symlink or reparse point is not allowed")
                if not stat.S_ISREG(file_stat.st_mode):
                    raise ValueError("entry is not a regular file")
                if resolved.parent != root_resolved:
                    raise ValueError("entry resolves outside the batch directory")
                size = int(file_stat.st_size)
                if size > limits.max_file_bytes:
                    raise ValueError(
                        f"file is {size} bytes; per-file limit is {limits.max_file_bytes}"
                    )
                files.append((path, size))
            except (OSError, ValueError) as exc:
                file_results.append(BatchFileResult(path.name, "FAILED", str(exc), 0, 0))

        total_size = sum(size for _, size in files)
        if total_size > limits.max_total_bytes:
            raise ValueError(
                f"Batch is {total_size} bytes; total limit is {limits.max_total_bytes}"
            )

        out_headers: Optional[List[str]] = None
        out_rows: List[Tuple[str, int, str, int, Sequence[str]]] = []
        schema_prefix = ["seq", "source_filename"]
        bytes_read = 0
        pages_processed = 0
        ingested_files: List[IngestedFile] = []

        for sequence, (path, expected_size) in enumerate(files, start=1):
            try:
                with path.open("rb") as source:
                    data = source.read(limits.max_file_bytes + 1)
                if len(data) != expected_size:
                    raise ValueError("file changed while it was being read")
                if len(data) > limits.max_file_bytes:
                    raise ValueError("file exceeded the per-file limit while being read")
                bytes_read += len(data)
                ingested, _ = self.ingest(path.name, data)
                if pages_processed + ingested.page_count > limits.max_pages:
                    raise ValueError(
                        f"processing this file would exceed the {limits.max_pages}-page batch limit"
                    )
                pages_processed += ingested.page_count
                if page_index >= ingested.page_count:
                    raise ValueError(f"page {page_1b} is outside this document")

                detection = self.detect_tables(ingested.file_id, data)
                if detection.status == "FAILED":
                    raise ValueError("table detection failed: " + "; ".join(detection.errors))
                page_candidates = [
                    candidate
                    for candidate in detection.candidates
                    if int(candidate.page_index) == page_index
                ]
                page_candidates.sort(
                    key=lambda candidate: (
                        float(candidate.bbox[1]),
                        float(candidate.bbox[0]),
                        -float(candidate.score),
                        candidate.candidate_id,
                    )
                )
                if not page_candidates:
                    raise ValueError(f"no table found on page {page_1b}")
                if table_index >= len(page_candidates):
                    raise ValueError(
                        f"table {table_index_1b} is outside the page's detected table range"
                    )

                candidate = page_candidates[table_index]
                headers, sliced = self.slice_grid(
                    self.candidate_to_grid(candidate),
                    mode=str(slice_mode),
                    row_1b=(None if row_1b in (None, "") else int(row_1b)),
                    col_1b=(None if col_1b in (None, "") else int(col_1b)),
                )
                full_headers = schema_prefix + list(headers)
                if out_headers is not None and full_headers != out_headers:
                    raise ValueError("sliced table schema does not match earlier files")
                out_headers = full_headers
                for row_index, values in enumerate(sliced):
                    out_rows.append(
                        (
                            ingested.file_id,
                            candidate.page_index,
                            candidate.candidate_id,
                            row_index,
                            [str(sequence), path.name]
                            + [("" if value is None else str(value)) for value in values],
                        )
                    )
                ingested_files.append(ingested)
                file_results.append(
                    BatchFileResult(path.name, "OK", "exported", len(data), ingested.page_count)
                )
            except Exception as exc:
                self._log("WARN", f"Batch file {path.name} failed: {exc}")
                file_results.append(
                    BatchFileResult(path.name, "FAILED", str(exc), expected_size, 0)
                )

        if out_headers is None:
            out_headers = schema_prefix
        file_results.sort(key=lambda item: (item.filename.casefold(), item.filename))
        report_object = {
            "limits": asdict(limits),
            "bytes_read": bytes_read,
            "pages_processed": pages_processed,
            "files": [asdict(item) for item in file_results],
        }
        report = canonical_json_bytes(report_object)
        manifest = self.build_manifest(ingested_files)

        if export_format == "csv":
            data = self._build_csv_bytes(table_headers=out_headers, table_rows=out_rows)
        else:
            data = export_mod.build_export_zip(
                table_headers=out_headers,
                table_rows=out_rows,
                manifest=manifest,
                events=self.get_events()[event_start:],
                include_xlsx=bool(include_xlsx),
                extra_members={"batch_report.json": report},
            )
        return BatchExtractionResult(
            data=data,
            report=report,
            files=file_results,
            bytes_read=bytes_read,
            pages_processed=pages_processed,
        )

    @staticmethod
    def _is_reparse_point(file_stat: Any) -> bool:
        return bool(getattr(file_stat, "st_file_attributes", 0) & 0x400)
