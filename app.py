from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from capabilities import detect_capabilities
from engine import Engine
from runplan import build_run_plan, run_plan_to_dict


@dataclass(frozen=True)
class Capabilities:
    pdf_text: bool
    pdf_images: bool
    pdf_tables: bool
    ocr: bool
    nlp: bool
    pandas: bool


def _caps_from_detect() -> Capabilities:
    d = detect_capabilities()

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
    has_pandas = "pandas" in export_providers or "pandas" in tables_providers

    has_ocr = ("pytesseract" in ocr_providers) and ("PIL" in ocr_providers)

    return Capabilities(
        pdf_text=has_pymupdf or has_pypdf,
        pdf_images=has_pymupdf,
        pdf_tables=has_pdf_tables,
        ocr=has_ocr,
        nlp=bool(nlp_providers),
        pandas=has_pandas,
    )


SS_CAPS_RAW = "caps_raw"
SS_CAPS = "caps"
SS_PLAN = "run_plan"
SS_PLAN_DICT = "run_plan_dict"

SS_DOCS = "docs"
SS_DOC_BYTES = "doc_bytes"
SS_DOC_ORDER = "doc_order"
SS_MERGED_BYTES = "merged_bytes"
SS_PAGE_MAP = "page_map"
SS_SELECTED_PAGE = "selected_page"

SS_DETECTIONS = "detections"
SS_CONFIRMED = "confirmed_slices"

SS_EVENTS = "events"


def _init_state() -> None:
    if SS_CAPS_RAW not in st.session_state:
        st.session_state[SS_CAPS_RAW] = detect_capabilities()
    if SS_CAPS not in st.session_state:
        st.session_state[SS_CAPS] = _caps_from_detect()
    if SS_PLAN not in st.session_state:
        st.session_state[SS_PLAN] = build_run_plan(st.session_state[SS_CAPS_RAW])
        st.session_state[SS_PLAN_DICT] = run_plan_to_dict(st.session_state[SS_PLAN])

    if SS_DOCS not in st.session_state:
        st.session_state[SS_DOCS] = []
    if SS_DOC_BYTES not in st.session_state:
        st.session_state[SS_DOC_BYTES] = {}
    if SS_DOC_ORDER not in st.session_state:
        st.session_state[SS_DOC_ORDER] = []
    if SS_MERGED_BYTES not in st.session_state:
        st.session_state[SS_MERGED_BYTES] = b""
    if SS_PAGE_MAP not in st.session_state:
        st.session_state[SS_PAGE_MAP] = []
    if SS_SELECTED_PAGE not in st.session_state:
        st.session_state[SS_SELECTED_PAGE] = 1

    if SS_DETECTIONS not in st.session_state:
        st.session_state[SS_DETECTIONS] = {}
    if SS_CONFIRMED not in st.session_state:
        st.session_state[SS_CONFIRMED] = {}

    if SS_EVENTS not in st.session_state:
        st.session_state[SS_EVENTS] = []


def _push_event(level: str, message: str) -> None:
    st.session_state[SS_EVENTS].append({"level": level, "message": message})


def _have_pypdf() -> bool:
    try:
        import pypdf  # type: ignore
        return True
    except Exception:
        return False


def _have_fitz() -> bool:
    try:
        import fitz  # type: ignore
        return True
    except Exception:
        return False
def _docs_by_id() -> Dict[str, Dict[str, Any]]:
    return {d["doc_id"]: d for d in st.session_state[SS_DOCS]}


def _doc_index(doc_id: str) -> int:
    for i, d in enumerate(st.session_state[SS_DOCS]):
        if d["doc_id"] == doc_id:
            return i
    return -1


def _merge_pdfs_in_order(pdf_blobs: List[bytes]) -> bytes:
    if _have_pypdf():
        from pypdf import PdfReader, PdfWriter  # type: ignore
        w = PdfWriter()
        for blob in pdf_blobs:
            r = PdfReader(BytesIO(blob))
            for p in r.pages:
                w.add_page(p)
        out = BytesIO()
        w.write(out)
        return out.getvalue()

    if _have_fitz():
        import fitz  # type: ignore
        out_doc = fitz.open()
        for blob in pdf_blobs:
            d = fitz.open(stream=blob, filetype="pdf")
            out_doc.insert_pdf(d)
        return out_doc.tobytes()

    raise RuntimeError("No PDF merge provider available.")


def _rebuild_merged_preview() -> bool:
    order = list(st.session_state[SS_DOC_ORDER])
    if not order:
        changed = st.session_state[SS_MERGED_BYTES] != b"" or st.session_state[SS_PAGE_MAP] != []
        st.session_state[SS_MERGED_BYTES] = b""
        st.session_state[SS_PAGE_MAP] = []
        st.session_state[SS_SELECTED_PAGE] = 1
        return changed

    by_id = _docs_by_id()

    blobs: List[bytes] = []
    page_map: List[Tuple[str, int]] = []

    for doc_id in order:
        if doc_id not in by_id:
            continue
        blobs.append(st.session_state[SS_DOC_BYTES][doc_id])
        pc = int(by_id[doc_id]["page_count"])
        for p in range(pc):
            page_map.append((doc_id, p))

    merged = _merge_pdfs_in_order(blobs)

    changed = (merged != st.session_state[SS_MERGED_BYTES]) or (page_map != st.session_state[SS_PAGE_MAP])

    st.session_state[SS_MERGED_BYTES] = merged
    st.session_state[SS_PAGE_MAP] = page_map

    total = len(page_map)
    if total <= 0:
        st.session_state[SS_SELECTED_PAGE] = 1
    else:
        cur = int(st.session_state[SS_SELECTED_PAGE])
        st.session_state[SS_SELECTED_PAGE] = max(1, min(cur, total))

    return changed


def ingest_uploaded_files(engine: Engine, uploaded_files: Optional[List[Any]]) -> bool:
    if not uploaded_files:
        return False

    changed = False
    existing = set(st.session_state[SS_DOC_BYTES].keys())

    for uf in uploaded_files:
        data = uf.getvalue()
        ing, _ = engine.ingest(uf.name, data)
        doc_id = ing.file_id

        if doc_id in existing:
            continue

        st.session_state[SS_DOCS].append(
            {
                "doc_id": doc_id,
                "filename": ing.filename,
                "page_count": int(ing.page_count),
                "sha256": ing.sha256,
                "size_bytes": int(ing.size_bytes),
            }
        )
        st.session_state[SS_DOC_BYTES][doc_id] = data
        st.session_state[SS_DOC_ORDER].append(doc_id)
        existing.add(doc_id)
        changed = True

    if changed:
        _push_event("INFO", "Documents ingested.")
    return changed


def delete_doc(doc_id: str) -> bool:
    if doc_id not in st.session_state[SS_DOC_BYTES]:
        return False

    st.session_state[SS_DOC_BYTES].pop(doc_id, None)
    st.session_state[SS_DETECTIONS].pop(doc_id, None)

    st.session_state[SS_DOCS] = [d for d in st.session_state[SS_DOCS] if d["doc_id"] != doc_id]
    st.session_state[SS_DOC_ORDER] = [x for x in st.session_state[SS_DOC_ORDER] if x != doc_id]

    keys_to_drop = [k for k in st.session_state[SS_CONFIRMED].keys() if k.startswith(doc_id + "|")]
    for k in keys_to_drop:
        st.session_state[SS_CONFIRMED].pop(k, None)

    _push_event("INFO", "Document removed.")
    return True


def apply_doc_order_from_positions(pos_map: Dict[str, int]) -> bool:
    current = list(st.session_state[SS_DOC_ORDER])
    if not current:
        return False

    pairs: List[Tuple[int, str]] = []
    for doc_id in current:
        pos = pos_map.get(doc_id)
        if pos is None:
            pos = 10**9
        pairs.append((int(pos), doc_id))

    pairs.sort(key=lambda x: (x[0], x[1]))
    new_order = [doc_id for _, doc_id in pairs]

    if new_order == current:
        return False

    st.session_state[SS_DOC_ORDER] = new_order
    _push_event("INFO", "Document order updated.")
    return True

st.set_page_config(page_title="pdf-etl-toolkit", layout="wide")

_init_state()

caps: Capabilities = st.session_state[SS_CAPS]
engine = Engine(st.session_state[SS_PLAN])

st.title("pdf-etl-toolkit")

with st.expander("Environment & Capabilities", expanded=False):
    st.json(st.session_state[SS_PLAN_DICT])

left, right = st.columns([1, 2])

state_changed = False

with left:
    st.subheader("Add PDFs")

    uploaded = st.file_uploader(
        "Drag and drop files here",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if ingest_uploaded_files(engine, uploaded):
        state_changed = True

    docs = st.session_state[SS_DOCS]

    if not docs:
        st.info("Upload one or more PDFs.")
    else:
        st.subheader("Documents")

        pos_map: Dict[str, int] = {}
        for d in docs:
            doc_id = d["doc_id"]
            c1, c2 = st.columns([3, 1])
            with c1:
                pos = st.number_input(
                    d["filename"],
                    min_value=1,
                    max_value=1000,
                    value=st.session_state[SS_DOC_ORDER].index(doc_id) + 1,
                    key=f"pos_{doc_id}",
                )
                pos_map[doc_id] = int(pos)
            with c2:
                if st.button("Remove", key=f"rm_{doc_id}"):
                    if delete_doc(doc_id):
                        state_changed = True

        if apply_doc_order_from_positions(pos_map):
            state_changed = True

        if state_changed:
            _rebuild_merged_preview()
            st.rerun()

        if st.session_state[SS_MERGED_BYTES]:
            st.subheader("Merged Output")
            st.download_button(
                "Download Merged PDF",
                data=st.session_state[SS_MERGED_BYTES],
                file_name="merged.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

with right:
    st.subheader("Preview")

    merged_bytes: bytes = st.session_state[SS_MERGED_BYTES]
    page_map = st.session_state[SS_PAGE_MAP]

    if not merged_bytes:
        st.info("Upload PDFs to enable preview.")
    else:
        total_pages = len(page_map)

        col1, col2 = st.columns([1, 3])
        with col1:
            page_input = st.number_input(
                "Go to page",
                min_value=1,
                max_value=total_pages,
                value=int(st.session_state[SS_SELECTED_PAGE]),
            )
            if page_input != st.session_state[SS_SELECTED_PAGE]:
                st.session_state[SS_SELECTED_PAGE] = int(page_input)
                st.rerun()

        b64 = base64.b64encode(merged_bytes).decode("utf-8")

        html = f"""
        <div style="height: 80vh;">
            <iframe
                src="data:application/pdf;base64,{b64}#page={st.session_state[SS_SELECTED_PAGE]}"
                width="100%"
                height="100%"
                style="border: none;"
            ></iframe>
        </div>
        """

        st.markdown(html, unsafe_allow_html=True)

from extract import detect_tables, TableCandidate
from export import build_export_zip
from utils import normalize_headers


st.divider()
st.header("Table Detection & Structuring")

if not caps.pdf_tables:
    st.info("Table detection unavailable in this environment.")
else:
    merged_bytes: bytes = st.session_state[SS_MERGED_BYTES]
    page_map = st.session_state[SS_PAGE_MAP]

    if not merged_bytes or not page_map:
        st.info("Upload PDFs to enable table detection.")
    else:
        total_pages = len(page_map)
        selected_page = int(st.session_state[SS_SELECTED_PAGE])
        selected_page = max(1, min(selected_page, total_pages))
        st.session_state[SS_SELECTED_PAGE] = selected_page

        doc_id, local_page = page_map[selected_page - 1]
        doc_bytes = st.session_state[SS_DOC_BYTES].get(doc_id)

        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.write(f"Document: `{doc_id}`")
        with col_b:
            if st.button("Detect Tables", key=f"detect_{doc_id}_{local_page}"):
                result = detect_tables(doc_id, doc_bytes, st.session_state[SS_PLAN])
                st.session_state[SS_DETECTIONS][doc_id] = [
                    c.__dict__ for c in result.candidates
                ]
                st.rerun()

        raw_candidates = st.session_state[SS_DETECTIONS].get(doc_id, [])
        candidates = [TableCandidate(**c) for c in raw_candidates]
        page_candidates = [c for c in candidates if c.page_index == local_page]
        page_candidates.sort(key=lambda c: (-c.score, c.bbox[1], c.bbox[0]))

        if not page_candidates:
            st.info("No detected tables on this page.")
        else:
            labels = [
                f"{i+1}. score={c.score:.3f} rows={c.row_count} cols={c.col_count}"
                for i, c in enumerate(page_candidates)
            ]

            idx = st.selectbox(
                "Candidate",
                list(range(len(page_candidates))),
                format_func=lambda i: labels[i],
            )

            chosen = page_candidates[int(idx)]

            def _candidate_to_matrix(c: TableCandidate):
                mat = [["" for _ in range(c.col_count)] for _ in range(c.row_count)]
                for cell in c.cells:
                    if 0 <= cell.row < c.row_count and 0 <= cell.col < c.col_count:
                        mat[cell.row][cell.col] = cell.text
                return mat

            matrix = _candidate_to_matrix(chosen)
            st.dataframe(matrix, use_container_width=True, height=300)

            rows = chosen.row_count
            cols = chosen.col_count

            st.subheader("Slice Configuration")

            r0, r1 = st.slider("Row Range", 0, rows - 1, (0, rows - 1))
            selected_cols = st.multiselect(
                "Columns",
                list(range(cols)),
                default=list(range(cols)),
            )

            if not selected_cols:
                st.error("Select at least one column.")
            else:
                header_mode = st.selectbox("Header Mode", ["Header Row", "No Header"])
                header_row = None
                if header_mode == "Header Row":
                    header_row = st.selectbox("Header Row Index", list(range(rows)))

                if header_row is None:
                    raw_headers = [f"col_{c}" for c in selected_cols]
                else:
                    raw_headers = [matrix[header_row][c] for c in selected_cols]

                normalized = normalize_headers(raw_headers)

                summary = {
                    "doc_id": doc_id,
                    "page_index": local_page,
                    "candidate_id": chosen.candidate_id,
                    "row_range": [int(r0), int(r1)],
                    "selected_cols": selected_cols,
                    "header_row": header_row,
                    "normalized_headers": normalized,
                }

                st.json(summary)

                slice_key = f"{doc_id}|{local_page}|{chosen.candidate_id}"
                locked = slice_key in st.session_state[SS_CONFIRMED]

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Confirm Slice", disabled=locked):
                        st.session_state[SS_CONFIRMED][slice_key] = summary
                        st.rerun()
                with c2:
                    if st.button("Unlock Slice", disabled=not locked):
                        st.session_state[SS_CONFIRMED].pop(slice_key, None)
                        st.rerun()


st.divider()
st.header("Export")

confirmed = list(st.session_state[SS_CONFIRMED].values())

if not confirmed:
    st.info("Confirm at least one slice to enable export.")
else:
    schemas = [tuple(s["normalized_headers"]) for s in confirmed]

    if not all(s == schemas[0] for s in schemas):
        st.error("Schema mismatch across confirmed slices.")
    else:
        headers = list(schemas[0])
        rows_out = []

        for s in sorted(confirmed, key=lambda x: (x["doc_id"], x["page_index"])):
            doc_id = s["doc_id"]
            page_i = s["page_index"]
            cand_id = s["candidate_id"]
            r0, r1 = s["row_range"]
            sel_cols = s["selected_cols"]
            header_row = s["header_row"]

            raw_cands = st.session_state[SS_DETECTIONS].get(doc_id, [])
            all_cands = [TableCandidate(**c) for c in raw_cands]
            target = next((c for c in all_cands if c.candidate_id == cand_id), None)
            if not target:
                continue

            def _candidate_to_matrix(c: TableCandidate):
                mat = [["" for _ in range(c.col_count)] for _ in range(c.row_count)]
                for cell in c.cells:
                    if 0 <= cell.row < c.row_count and 0 <= cell.col < c.col_count:
                        mat[cell.row][cell.col] = cell.text
                return mat

            mat = _candidate_to_matrix(target)

            for r in range(r0, r1 + 1):
                if header_row is not None and r == header_row:
                    continue
                row_vals = [
                    mat[r][c] if r < len(mat) and c < len(mat[r]) else ""
                    for c in sel_cols
                ]
                rows_out.append((doc_id, page_i, cand_id, r, row_vals))

        include_xlsx = st.checkbox("Include XLSX (if available)", disabled=not caps.pandas)

        manifest = {
            "documents": st.session_state[SS_DOCS],
            "schema_headers": headers,
            "confirmed_slices": confirmed,
        }

        events = st.session_state.get(SS_EVENTS, [])

        zip_bytes = build_export_zip(
            table_headers=headers,
            table_rows=rows_out,
            manifest=manifest,
            events=events,
            include_xlsx=bool(include_xlsx),
        )

        st.download_button(
            "Download Export Pack (ZIP)",
            data=zip_bytes,
            file_name="export_pack.zip",
            mime="application/zip",
            use_container_width=True,
        )

with st.expander("Diagnostics", expanded=False):
    st.json({"documents": st.session_state[SS_DOCS]})
    st.json({"events": st.session_state.get(SS_EVENTS, [])})