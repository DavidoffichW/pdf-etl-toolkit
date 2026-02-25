from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Capabilities:
    pdf_text: bool
    pdf_images: bool
    pdf_tables: bool
    ocr: bool
    nlp: bool
    pandas: bool


SS_CAPS_RAW = "caps_raw"
SS_CAPS = "caps"
SS_PLAN = "run_plan"
SS_PLAN_DICT = "run_plan_dict"

SS_DOCS = "docs"
SS_DOC_BYTES = "doc_bytes"
SS_DOC_ORDER = "doc_order"

SS_ACTIVE_DOC = "active_doc"
SS_ACTIVE_PAGE = "active_page"

SS_MERGED_BYTES = "merged_bytes"
SS_PAGE_MAP = "page_map"

SS_DETECTIONS = "detections"
SS_CONFIRMED = "confirmed_slices"
SS_EVENTS = "events"

SS_UPLOADER_KEY = "uploader_widget"
SS_UPLOADER_TOKEN = "uploader_token"


def caps_from_detect(d: Dict[str, Any]) -> Capabilities:
    pdf_caps = d.get("pdf")
    tables_caps = d.get("tables")
    ocr_caps = d.get("ocr")
    export_caps = d.get("export")
    nlp_caps = d.get("nlp")

    pdf_providers = set(pdf_caps.providers) if pdf_caps else set()
    tables_providers = set(tables_caps.providers) if tables_caps else set()
    ocr_providers = set(ocr_caps.providers) if ocr_caps else set()
    export_providers = set(export_caps.providers) if export_caps else set()
    nlp_providers = set(nlp_caps.providers) if nlp_caps else set()

    has_pymupdf = "fitz" in pdf_providers
    has_pypdf = "pypdf" in pdf_providers

    has_pdf_tables = ("pdfplumber" in tables_providers) or ("pymupdf_tables" in tables_providers)
    has_pandas = ("pandas" in export_providers) or ("pandas" in tables_providers)
    has_ocr = ("pytesseract" in ocr_providers) and ("PIL" in ocr_providers)

    return Capabilities(
        pdf_text=has_pymupdf or has_pypdf,
        pdf_images=has_pymupdf,
        pdf_tables=has_pdf_tables,
        ocr=has_ocr,
        nlp=bool(nlp_providers),
        pandas=has_pandas,
    )


def init_state(*, caps_raw: Dict[str, Any], caps: Capabilities, plan: Any, plan_dict: Dict[str, Any]) -> None:
    import streamlit as st

    if SS_CAPS_RAW not in st.session_state:
        st.session_state[SS_CAPS_RAW] = caps_raw
    if SS_CAPS not in st.session_state:
        st.session_state[SS_CAPS] = caps
    if SS_PLAN not in st.session_state:
        st.session_state[SS_PLAN] = plan
    if SS_PLAN_DICT not in st.session_state:
        st.session_state[SS_PLAN_DICT] = plan_dict

    if SS_DOCS not in st.session_state:
        st.session_state[SS_DOCS] = []
    if SS_DOC_BYTES not in st.session_state:
        st.session_state[SS_DOC_BYTES] = {}
    if SS_DOC_ORDER not in st.session_state:
        st.session_state[SS_DOC_ORDER] = []

    if SS_ACTIVE_DOC not in st.session_state:
        st.session_state[SS_ACTIVE_DOC] = None
    if SS_ACTIVE_PAGE not in st.session_state:
        st.session_state[SS_ACTIVE_PAGE] = 1

    if SS_MERGED_BYTES not in st.session_state:
        st.session_state[SS_MERGED_BYTES] = b""
    if SS_PAGE_MAP not in st.session_state:
        st.session_state[SS_PAGE_MAP] = []

    if SS_DETECTIONS not in st.session_state:
        st.session_state[SS_DETECTIONS] = {}
    if SS_CONFIRMED not in st.session_state:
        st.session_state[SS_CONFIRMED] = {}

    if SS_EVENTS not in st.session_state:
        st.session_state[SS_EVENTS] = []

    if SS_UPLOADER_TOKEN not in st.session_state:
        st.session_state[SS_UPLOADER_TOKEN] = 0


def get_uploader_token() -> int:
    import streamlit as st
    return int(st.session_state.get(SS_UPLOADER_TOKEN, 0))


def bump_uploader_token() -> None:
    import streamlit as st
    st.session_state[SS_UPLOADER_TOKEN] = int(st.session_state.get(SS_UPLOADER_TOKEN, 0)) + 1


def push_event(level: str, message: str) -> None:
    import streamlit as st
    st.session_state[SS_EVENTS].append({"level": level, "message": message})


def get_docs() -> List[Dict[str, Any]]:
    import streamlit as st
    order = list(st.session_state[SS_DOC_ORDER])
    by_id = {d["doc_id"]: d for d in st.session_state[SS_DOCS]}
    out = []
    for doc_id in order:
        if doc_id in by_id:
            out.append(by_id[doc_id])
    return out


def get_doc_bytes(doc_id: str) -> bytes:
    import streamlit as st
    return st.session_state[SS_DOC_BYTES][doc_id]


def set_doc_bytes(doc_id: str, blob: bytes) -> None:
    import streamlit as st
    st.session_state[SS_DOC_BYTES][doc_id] = blob


def set_docs(docs: List[Dict[str, Any]]) -> None:
    import streamlit as st
    st.session_state[SS_DOCS] = docs


def set_order(order: List[str]) -> None:
    import streamlit as st
    st.session_state[SS_DOC_ORDER] = order


def get_order() -> List[str]:
    import streamlit as st
    return list(st.session_state[SS_DOC_ORDER])


def get_active_doc_id() -> Optional[str]:
    import streamlit as st
    return st.session_state[SS_ACTIVE_DOC]


def set_active_doc_id(doc_id: Optional[str]) -> None:
    import streamlit as st
    st.session_state[SS_ACTIVE_DOC] = doc_id
    st.session_state[SS_ACTIVE_PAGE] = 1


def get_active_doc() -> Optional[Dict[str, Any]]:
    docs = get_docs()
    active = get_active_doc_id()
    if active is None:
        return docs[0] if docs else None
    for d in docs:
        if d["doc_id"] == active:
            return d
    return docs[0] if docs else None


def get_active_page() -> int:
    import streamlit as st
    return int(st.session_state[SS_ACTIVE_PAGE])


def set_active_page(page: int) -> None:
    import streamlit as st
    st.session_state[SS_ACTIVE_PAGE] = int(page)


def get_merged_bytes() -> bytes:
    import streamlit as st
    return st.session_state[SS_MERGED_BYTES]


def set_merged_bytes(blob: bytes) -> None:
    import streamlit as st
    st.session_state[SS_MERGED_BYTES] = blob


def get_page_map() -> List[Tuple[str, int]]:
    import streamlit as st
    return list(st.session_state[SS_PAGE_MAP])


def set_page_map(m: List[Tuple[str, int]]) -> None:
    import streamlit as st
    st.session_state[SS_PAGE_MAP] = m


def replace_doc_id(old_id: str, new_id: str, new_meta: Dict[str, Any], new_blob: bytes) -> None:
    import streamlit as st

    docs = list(st.session_state[SS_DOCS])
    for i, d in enumerate(docs):
        if d["doc_id"] == old_id:
            docs[i] = new_meta
            break
    st.session_state[SS_DOCS] = docs

    b = dict(st.session_state[SS_DOC_BYTES])
    b.pop(old_id, None)
    b[new_id] = new_blob
    st.session_state[SS_DOC_BYTES] = b

    order = [new_id if x == old_id else x for x in st.session_state[SS_DOC_ORDER]]
    st.session_state[SS_DOC_ORDER] = order

    if st.session_state[SS_ACTIVE_DOC] == old_id:
        st.session_state[SS_ACTIVE_DOC] = new_id
        st.session_state[SS_ACTIVE_PAGE] = 1

    det = dict(st.session_state[SS_DETECTIONS])
    if old_id in det:
        det.pop(old_id, None)
    st.session_state[SS_DETECTIONS] = det

    conf = dict(st.session_state[SS_CONFIRMED])
    for k in list(conf.keys()):
        if k.startswith(old_id + "|"):
            conf.pop(k, None)
    st.session_state[SS_CONFIRMED] = conf