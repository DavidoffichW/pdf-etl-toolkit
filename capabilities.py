from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    providers: List[str]
    missing_modules: List[str]
    notes: Optional[str]


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def detect_capabilities() -> Dict[str, Capability]:
    pdf_providers: List[str] = []
    pdf_missing: List[str] = []
    if _try_import("fitz"):
        pdf_providers.append("fitz")
    else:
        pdf_missing.append("fitz")
    if _try_import("pypdf"):
        pdf_providers.append("pypdf")
    else:
        pdf_missing.append("pypdf")

    tables_providers: List[str] = []
    tables_missing: List[str] = []
    if _try_import("fitz"):
        tables_providers.append("pymupdf_tables")
    else:
        tables_missing.append("fitz")
    if _try_import("pdfplumber"):
        tables_providers.append("pdfplumber")
    else:
        tables_missing.append("pdfplumber")

    ocr_providers: List[str] = []
    ocr_missing: List[str] = []
    if _try_import("pytesseract"):
        ocr_providers.append("pytesseract")
    else:
        ocr_missing.append("pytesseract")
    if _try_import("PIL"):
        ocr_providers.append("PIL")
    else:
        ocr_missing.append("PIL")

    export_providers: List[str] = ["csv"]
    export_missing: List[str] = []
    if _try_import("pandas"):
        export_providers.append("pandas")
    else:
        export_missing.append("pandas")

    caps: Dict[str, Capability] = {
        "pdf": Capability(
            name="pdf",
            available=len(pdf_providers) > 0,
            providers=pdf_providers,
            missing_modules=pdf_missing,
            notes=None,
        ),
        "tables": Capability(
            name="tables",
            available=len(tables_providers) > 0,
            providers=tables_providers,
            missing_modules=tables_missing,
            notes="pymupdf_tables requires fitz; pdfplumber is optional alternative",
        ),
        "ocr": Capability(
            name="ocr",
            available=("pytesseract" in ocr_providers) and ("PIL" in ocr_providers),
            providers=ocr_providers,
            missing_modules=ocr_missing,
            notes="OCR requires both pytesseract and PIL",
        ),
        "export": Capability(
            name="export",
            available=True,
            providers=export_providers,
            missing_modules=export_missing,
            notes="CSV is always available; pandas enables XLSX",
        ),
    }
    return caps