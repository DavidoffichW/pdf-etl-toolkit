from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from capabilities import Capability, detect_capabilities


@dataclass(frozen=True)
class ProviderPlan:
    capability: str
    provider: Optional[str]
    status: str
    reason: Optional[str]


@dataclass(frozen=True)
class RunPlan:
    pdf: ProviderPlan
    tables: ProviderPlan
    ocr: ProviderPlan
    export: ProviderPlan


def _pick_first_available(cap: Capability, preferred: list[str]) -> Optional[str]:
    available = set(cap.providers)
    for p in preferred:
        if p in available:
            return p
    return None


def build_run_plan(capabilities: Optional[Dict[str, Capability]] = None) -> RunPlan:
    caps = capabilities if capabilities is not None else detect_capabilities()

    pdf_cap = caps["pdf"]
    tables_cap = caps["tables"]
    ocr_cap = caps["ocr"]
    export_cap = caps["export"]

    pdf_provider = _pick_first_available(pdf_cap, ["fitz", "pypdf"])
    if pdf_provider is None:
        raise RuntimeError("No PDF provider available. Install either 'fitz' or 'pypdf'.")

    pdf_plan = ProviderPlan(
        capability="pdf",
        provider=pdf_provider,
        status="OK",
        reason=None,
    )

    tables_provider = _pick_first_available(tables_cap, ["pymupdf_tables", "pdfplumber"])
    if tables_provider is None:
        tables_plan = ProviderPlan(
            capability="tables",
            provider=None,
            status="DISABLED",
            reason="No table provider available. Install 'fitz' (PyMuPDF) and/or 'pdfplumber'.",
        )
    else:
        tables_status = "OK"
        tables_reason = None
        tables_plan = ProviderPlan(
            capability="tables",
            provider=tables_provider,
            status=tables_status,
            reason=tables_reason,
        )

    ocr_required = ("pytesseract" in ocr_cap.providers) and ("PIL" in ocr_cap.providers)
    if not ocr_required:
        ocr_plan = ProviderPlan(
            capability="ocr",
            provider=None,
            status="DISABLED",
            reason="OCR unavailable. Requires both 'pytesseract' and 'PIL'.",
        )
    else:
        ocr_plan = ProviderPlan(
            capability="ocr",
            provider="pytesseract",
            status="OK",
            reason=None,
        )

    export_provider = "csv"
    export_status = "OK"
    export_reason = None
    export_plan = ProviderPlan(
        capability="export",
        provider=export_provider,
        status=export_status,
        reason=export_reason,
    )

    return RunPlan(
        pdf=pdf_plan,
        tables=tables_plan,
        ocr=ocr_plan,
        export=export_plan,
    )


def run_plan_to_dict(plan: RunPlan) -> Dict[str, Dict[str, Optional[str]]]:
    return {
        "pdf": {
            "provider": plan.pdf.provider,
            "status": plan.pdf.status,
            "reason": plan.pdf.reason,
        },
        "tables": {
            "provider": plan.tables.provider,
            "status": plan.tables.status,
            "reason": plan.tables.reason,
        },
        "ocr": {
            "provider": plan.ocr.provider,
            "status": plan.ocr.status,
            "reason": plan.ocr.reason,
        },
        "export": {
            "provider": plan.export.provider,
            "status": plan.export.status,
            "reason": plan.export.reason,
        },
    }