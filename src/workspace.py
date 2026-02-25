from __future__ import annotations

from io import BytesIO
from typing import Any, List, Optional, Tuple

import state


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


def _merge_pdfs(blobs: List[bytes]) -> bytes:
    if _have_pypdf():
        from pypdf import PdfReader, PdfWriter  # type: ignore
        w = PdfWriter()
        for blob in blobs:
            r = PdfReader(BytesIO(blob))
            for p in r.pages:
                w.add_page(p)
        out = BytesIO()
        w.write(out)
        return out.getvalue()

    if _have_fitz():
        import fitz  # type: ignore
        out_doc = fitz.open()
        for blob in blobs:
            d = fitz.open(stream=blob, filetype="pdf")
            out_doc.insert_pdf(d)
        return out_doc.tobytes()

    raise RuntimeError("No PDF merge provider available.")


def _extract_pages(blob: bytes, start_1b: int, end_1b: int) -> bytes:
    start = start_1b - 1
    end = end_1b - 1

    if _have_pypdf():
        from pypdf import PdfReader, PdfWriter  # type: ignore
        r = PdfReader(BytesIO(blob))
        w = PdfWriter()
        end = min(end, len(r.pages) - 1)
        for i in range(start, end + 1):
            w.add_page(r.pages[i])
        out = BytesIO()
        w.write(out)
        return out.getvalue()

    if _have_fitz():
        import fitz  # type: ignore
        src = fitz.open(stream=blob, filetype="pdf")
        out = fitz.open()
        end = min(end, src.page_count - 1)
        out.insert_pdf(src, from_page=start, to_page=end)
        return out.tobytes()

    raise RuntimeError("No PDF provider available.")


def _delete_pages(blob: bytes, start_1b: int, end_1b: int) -> bytes:
    start = start_1b - 1
    end = end_1b - 1

    if _have_pypdf():
        from pypdf import PdfReader, PdfWriter  # type: ignore
        r = PdfReader(BytesIO(blob))
        w = PdfWriter()
        n = len(r.pages)
        end = min(end, n - 1)
        for i in range(n):
            if start <= i <= end:
                continue
            w.add_page(r.pages[i])
        out = BytesIO()
        w.write(out)
        return out.getvalue()

    if _have_fitz():
        import fitz  # type: ignore
        src = fitz.open(stream=blob, filetype="pdf")
        out = fitz.open()
        keep = [i for i in range(src.page_count) if not (start <= i <= end)]
        for i in keep:
            out.insert_pdf(src, from_page=i, to_page=i)
        return out.tobytes()

    raise RuntimeError("No PDF provider available.")


def ingest_uploaded(engine: Any, uploaded_files: Optional[List[Any]]) -> bool:
    if not uploaded_files:
        return False

    existing = set(state.get_order())
    changed = False

    docs = list(state.get_docs())
    doc_by_id = {d["doc_id"]: d for d in docs}

    for uf in uploaded_files:
        data = uf.getvalue()
        ing, _ = engine.ingest(uf.name, data)
        doc_id = ing.file_id

        if doc_id in existing or doc_id in doc_by_id:
            continue

        docs.append(
            {
                "doc_id": doc_id,
                "filename": ing.filename,
                "page_count": int(ing.page_count),
                "sha256": ing.sha256,
                "size_bytes": int(ing.size_bytes),
            }
        )
        state.set_doc_bytes(doc_id, data)

        order = state.get_order()
        order.append(doc_id)
        state.set_order(order)

        if state.get_active_doc_id() is None:
            state.set_active_doc_id(doc_id)

        changed = True

    if changed:
        state.set_docs(docs)
        state.push_event("INFO", "Documents ingested.")
        rebuild_merged()

    return changed


def rebuild_merged() -> None:
    docs = state.get_docs()
    order = [d["doc_id"] for d in docs]
    by_id = {d["doc_id"]: d for d in docs}

    blobs: List[bytes] = []
    page_map: List[Tuple[str, int]] = []

    for doc_id in order:
        blob = state.get_doc_bytes(doc_id)
        blobs.append(blob)
        pc = int(by_id[doc_id]["page_count"])
        for p in range(pc):
            page_map.append((doc_id, p))

    merged = _merge_pdfs(blobs) if blobs else b""
    state.set_merged_bytes(merged)
    state.set_page_map(page_map)


def apply_order(new_order: List[str]) -> bool:
    docs = state.get_docs()
    if not docs:
        return False

    by_id = {d["doc_id"]: d for d in docs}
    norm = [x for x in new_order if x in by_id]
    if len(norm) != len(by_id):
        for d in docs:
            if d["doc_id"] not in norm:
                norm.append(d["doc_id"])

    current = [d["doc_id"] for d in docs]
    if norm == current:
        return False

    state.set_order(norm)
    state.push_event("INFO", "Order updated.")
    return True


def remove_doc(doc_id: str) -> bool:
    docs = state.get_docs()
    if not any(d["doc_id"] == doc_id for d in docs):
        return False

    import streamlit as st

    b = dict(st.session_state[state.SS_DOC_BYTES])
    b.pop(doc_id, None)
    st.session_state[state.SS_DOC_BYTES] = b

    docs = [d for d in docs if d["doc_id"] != doc_id]
    state.set_docs(docs)

    order = [d["doc_id"] for d in docs]
    state.set_order(order)

    active = state.get_active_doc_id()
    if active == doc_id:
        state.set_active_doc_id(order[0] if order else None)

    rebuild_merged()
    state.push_event("INFO", "Document removed.")
    return True


def move_up(doc_id: str) -> bool:
    order = state.get_order()
    if doc_id not in order:
        return False
    i = order.index(doc_id)
    if i <= 0:
        return False
    order[i - 1], order[i] = order[i], order[i - 1]
    state.set_order(order)
    state.push_event("INFO", "Order updated.")
    return True


def move_down(doc_id: str) -> bool:
    order = state.get_order()
    if doc_id not in order:
        return False
    i = order.index(doc_id)
    if i >= len(order) - 1:
        return False
    order[i + 1], order[i] = order[i], order[i + 1]
    state.set_order(order)
    state.push_event("INFO", "Order updated.")
    return True


def extract_range_to_new_doc(engine: Any, doc_id: str, start_page: int, end_page: int) -> bool:
    if start_page > end_page:
        start_page, end_page = end_page, start_page

    docs = state.get_docs()
    src_meta = next((d for d in docs if d["doc_id"] == doc_id), None)
    if src_meta is None:
        return False

    src_blob = state.get_doc_bytes(doc_id)
    out_blob = _extract_pages(src_blob, start_page, end_page)

    base = src_meta["filename"].rsplit(".", 1)[0]
    new_name = f"{base}__extract_{start_page}-{end_page}.pdf"

    ing, _ = engine.ingest(new_name, out_blob)
    new_id = ing.file_id

    if any(d["doc_id"] == new_id for d in docs):
        return False

    docs.append(
        {
            "doc_id": new_id,
            "filename": ing.filename,
            "page_count": int(ing.page_count),
            "sha256": ing.sha256,
            "size_bytes": int(ing.size_bytes),
        }
    )
    state.set_docs(docs)
    state.set_doc_bytes(new_id, out_blob)

    order = state.get_order()
    order.append(new_id)
    state.set_order(order)

    state.set_active_doc_id(new_id)

    rebuild_merged()
    state.push_event("INFO", "Extracted range added as new document.")
    return True


def delete_range_in_doc(engine: Any, doc_id: str, start_page: int, end_page: int) -> bool:
    if start_page > end_page:
        start_page, end_page = end_page, start_page

    docs = state.get_docs()
    src_meta = next((d for d in docs if d["doc_id"] == doc_id), None)
    if src_meta is None:
        return False

    src_blob = state.get_doc_bytes(doc_id)
    out_blob = _delete_pages(src_blob, start_page, end_page)

    base = src_meta["filename"].rsplit(".", 1)[0]
    new_name = f"{base}__deleted_{start_page}-{end_page}.pdf"

    ing, _ = engine.ingest(new_name, out_blob)
    new_id = ing.file_id

    new_meta = {
        "doc_id": new_id,
        "filename": src_meta["filename"],
        "page_count": int(ing.page_count),
        "sha256": ing.sha256,
        "size_bytes": int(ing.size_bytes),
    }

    state.replace_doc_id(doc_id, new_id, new_meta, out_blob)

    rebuild_merged()
    state.push_event("INFO", "Deleted page range in active document.")
    return True