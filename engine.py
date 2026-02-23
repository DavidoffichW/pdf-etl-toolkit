from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Tuple
from io import BytesIO

from utils import sha256_bytes, stable_id, utc_now_iso, canonical_json_bytes
from runplan import RunPlan


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

    
    # Event Logging
    

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

    
    # Ingest
    

    def ingest(self, filename: str, data: bytes) -> Tuple[IngestedFile, List[PageInfo]]:
        """
        Deterministic ingest.
        Computes hash, assigns file_id, extracts page metadata.
        """
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

    
    # Page Metadata Extraction
    

    def _extract_page_metadata(
        self, file_id: str, data: bytes
    ) -> Tuple[int, List[PageInfo]]:

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
            page_infos: List[PageInfo] = []
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

    
    # Manifest Builder (Ephemeral)
    

    def build_manifest(
        self,
        ingested_files: List[IngestedFile],
    ) -> Dict[str, Any]:

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

    
    # Manifest Bytes
    

    def manifest_bytes(self, manifest: Dict[str, Any]) -> bytes:
        return canonical_json_bytes(manifest)