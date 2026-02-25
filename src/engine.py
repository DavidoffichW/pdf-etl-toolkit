from __future__ import annotations

from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
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

            doc = fitz.open(stream=data, filetype="pdf")
            page_infos: List[PageInfo] = []
            for i in range(len(doc)):
                page = doc[i]
                rect = page.rect
                page_infos.append(
                    PageInfo(
                        file_id=file_id,
                        page_index=i,
                        width=float(rect.width),
                        height=float(rect.height),
                    )
                )
            return len(doc), page_infos

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
            "timestamp": utc_now_iso(),
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
            "event_count": len(self._events),
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
        blob: bytes,
        selected_candidate_indices: Sequence[int],
        slice_configs: Dict[int, Dict[str, Any]],
        docs_meta: Sequence[Dict[str, Any]],
        export_format: str,
        include_xlsx: bool,
    ) -> bytes:
        res = self.detect_tables(file_id=file_id, data=blob)
        if not res.candidates:
            self._log("WARN", "No candidates available for export.")
            if export_format == "csv":
                return b""
            manifest = self.build_manifest(self.ingested_from_docs_meta(docs_meta))
            return export_mod.build_export_zip(
                table_headers=[],
                table_rows=[],
                manifest=manifest,
                events=self.get_events(),
                include_xlsx=False,
            )

        indices = [int(i) for i in selected_candidate_indices]
        indices = [i for i in indices if 0 <= i < len(res.candidates)]
        if not indices:
            self._log("WARN", "No valid candidate indices selected.")
            if export_format == "csv":
                return b""
            manifest = self.build_manifest(self.ingested_from_docs_meta(docs_meta))
            return export_mod.build_export_zip(
                table_headers=[],
                table_rows=[],
                manifest=manifest,
                events=self.get_events(),
                include_xlsx=False,
            )

        out_headers: Optional[List[str]] = None
        out_rows: List[Tuple[str, int, str, int, Sequence[str]]] = []

        for idx in indices:
            cand = res.candidates[idx]
            grid = self.candidate_to_grid(cand)

            cfg = slice_configs.get(idx, {})
            mode = str(cfg.get("mode", "table"))
            row_1b = cfg.get("row")
            col_1b = cfg.get("column")

            try:
                headers, sliced = self.slice_grid(
                    grid,
                    mode=mode,
                    row_1b=(None if row_1b in (None, "") else int(row_1b)),
                    col_1b=(None if col_1b in (None, "") else int(col_1b)),
                )
            except Exception as e:
                self._log("WARN", f"Slice failed for candidate idx={idx}: {e}")
                continue

            if out_headers is None:
                out_headers = list(headers)
            else:
                if list(headers) != list(out_headers):
                    self._log("WARN", f"Schema mismatch for candidate idx={idx}; skipping.")
                    continue

            for r_i, row_vals in enumerate(sliced):
                out_rows.append(
                    (
                        cand.file_id,
                        int(cand.page_index),
                        str(cand.candidate_id),
                        int(r_i),
                        list(row_vals),
                    )
                )

        if out_headers is None:
            self._log("WARN", "No rows produced after slicing.")
            out_headers = []

        manifest = self.build_manifest(self.ingested_from_docs_meta(docs_meta))

        if export_format == "csv":
            return self._build_csv_bytes(table_headers=out_headers, table_rows=out_rows)

        return export_mod.build_export_zip(
            table_headers=out_headers,
            table_rows=out_rows,
            manifest=manifest,
            events=self.get_events(),
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
    ) -> bytes:
        p = Path(directory_path)
        if not p.exists() or not p.is_dir():
            raise ValueError("Invalid directory path")

        files = sorted([x for x in p.iterdir() if x.is_file() and x.suffix.lower() == ".pdf"], key=lambda x: x.name)
        if not files:
            raise ValueError("No PDF files found in directory")

        page_index = int(page_1b) - 1
        if page_index < 0:
            raise ValueError("page must be >= 1")

        t_index = int(table_index_1b) - 1
        if t_index < 0:
            raise ValueError("table index must be >= 1")

        out_headers: Optional[List[str]] = None
        out_rows: List[Tuple[str, int, str, int, Sequence[str]]] = []

        schema_prefix = ["seq", "source_filename"]

        for seq, fp in enumerate(files, start=1):
            try:
                data = fp.read_bytes()
            except Exception as e:
                self._log("WARN", f"Failed to read file seq={seq} name={fp.name}: {e}")
                continue

            ing, _ = self.ingest(fp.name, data)
            det = self.detect_tables(ing.file_id, data)
            if not det.candidates:
                self._log("WARN", f"No candidates for seq={seq} name={fp.name}")
                continue

            page_cands = [c for c in det.candidates if int(c.page_index) == page_index]
            if not page_cands:
                self._log("WARN", f"No tables on page={page_1b} for seq={seq} name={fp.name}")
                continue

            page_cands = sorted(page_cands, key=lambda c: (-c.score, c.bbox[1], c.bbox[0]))

            if t_index >= len(page_cands):
                self._log(
                    "WARN",
                    f"Table index {table_index_1b} out of range on page={page_1b} for seq={seq} name={fp.name}",
                )
                continue

            cand = page_cands[t_index]
            grid = self.candidate_to_grid(cand)

            try:
                headers, sliced = self.slice_grid(
                    grid,
                    mode=str(slice_mode),
                    row_1b=(None if row_1b in (None, "") else int(row_1b)),
                    col_1b=(None if col_1b in (None, "") else int(col_1b)),
                )
            except Exception as e:
                self._log("WARN", f"Slice failed seq={seq} name={fp.name}: {e}")
                continue

            full_headers = schema_prefix + list(headers)
            if out_headers is None:
                out_headers = full_headers
            else:
                if full_headers != out_headers:
                    self._log("WARN", f"Schema mismatch seq={seq} name={fp.name}; skipping file.")
                    continue

            for r_i, row_vals in enumerate(sliced):
                values = [str(seq), fp.name] + [("" if v is None else str(v)) for v in list(row_vals)]
                out_rows.append(
                    (
                        ing.file_id,
                        int(cand.page_index),
                        str(cand.candidate_id),
                        int(r_i),
                        values,
                    )
                )

        if out_headers is None:
            out_headers = schema_prefix

        manifest = self.build_manifest(
            [
                IngestedFile(
                    file_id="batch",
                    filename=str(p),
                    size_bytes=0,
                    sha256="",
                    page_count=0,
                )
            ]
        )

        if export_format == "csv":
            return self._build_csv_bytes(table_headers=out_headers, table_rows=out_rows)

        return export_mod.build_export_zip(
            table_headers=out_headers,
            table_rows=out_rows,
            manifest=manifest,
            events=self.get_events(),
            include_xlsx=bool(include_xlsx),
        )