from __future__ import annotations

import csv
import json
import zipfile
from io import BytesIO, StringIO
from typing import Any, Dict, List, Tuple

import streamlit as st

import state
from detection_ui import SS_SLICE_CONFIG


SS_INTERACTIVE_EXPORT = "interactive_export_result"
SS_BATCH_EXPORT = "batch_export_result"


def _collect_selected(doc_id: str) -> List[int]:
    confirmed = st.session_state[state.SS_CONFIRMED]
    indices: List[int] = []
    for key, val in confirmed.items():
        if not val:
            continue
        if key.startswith(doc_id + "|"):
            try:
                idx = int(key.split("|")[1])
                indices.append(idx)
            except Exception:
                continue
    return sorted(indices)


def _parse_csv_preview(csv_bytes: bytes, *, max_rows: int) -> Tuple[List[str], List[List[str]]]:
    try:
        text = csv_bytes.decode("utf-8", errors="replace")
    except Exception:
        return [], []
    buf = StringIO(text)
    reader = csv.reader(buf)
    rows: List[List[str]] = []
    headers: List[str] = []
    for i, r in enumerate(reader):
        if i == 0:
            headers = list(r)
            continue
        rows.append(list(r))
        if len(rows) >= int(max_rows):
            break
    return headers, rows


def _build_jsonl_preview_from_csv(csv_bytes: bytes, *, max_lines: int) -> str:
    headers, rows = _parse_csv_preview(csv_bytes, max_rows=max_lines)
    if not headers:
        return ""
    out_lines: List[str] = []
    for row in rows:
        obj: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            obj[str(h)] = row[i] if i < len(row) else ""
        out_lines.append(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        if len(out_lines) >= int(max_lines):
            break
    return "\n".join(out_lines) + ("\n" if out_lines else "")


def _extract_zip_members(zip_bytes: bytes) -> Dict[str, bytes]:
    out: Dict[str, bytes] = {}
    try:
        z = zipfile.ZipFile(BytesIO(zip_bytes))
    except Exception:
        return out
    for name in z.namelist():
        try:
            out[name] = z.read(name)
        except Exception:
            continue
    return out


def _render_tabular_preview(*, label: str, csv_bytes: bytes) -> None:
    headers, rows = _parse_csv_preview(csv_bytes, max_rows=200)
    if not headers:
        st.info("No CSV preview available.")
        return
    data_rows: List[Dict[str, Any]] = []
    for r in rows:
        obj: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            obj[str(h)] = r[i] if i < len(r) else ""
        data_rows.append(obj)
    st.caption(label)
    st.dataframe(data_rows, use_container_width=True, height=280)


def render_export_panel(engine: Any) -> None:
    if SS_INTERACTIVE_EXPORT not in st.session_state:
        st.session_state[SS_INTERACTIVE_EXPORT] = {}
    if SS_BATCH_EXPORT not in st.session_state:
        st.session_state[SS_BATCH_EXPORT] = {}

    docs = state.get_docs()
    if not docs:
        st.info("No documents available.")
        return

    active = state.get_active_doc()
    if active is None:
        st.info("Select a document.")
        return

    doc_id = active["doc_id"]
    candidates = st.session_state[state.SS_DETECTIONS].get(doc_id)
    if not candidates:
        st.info("Run detection before exporting.")
        return

    st.subheader("Interactive Export")

    selected_indices = _collect_selected(doc_id)
    export_format = st.selectbox(
        "Export Format",
        options=["csv", "zip"],
        index=0,
        key="interactive_export_format",
    )

    include_xlsx = False
    if export_format == "zip":
        include_xlsx = st.checkbox(
            "Include XLSX (if supported)",
            value=False,
            key="interactive_include_xlsx",
        )

    if not selected_indices:
        st.info("Select at least one detected table.")
    else:
        if export_format == "csv" and len(selected_indices) != 1:
            st.warning("CSV export supports exactly one selected table. Use ZIP for multi-table export.")

        if st.button("Generate Export", use_container_width=True):
            if export_format == "csv" and len(selected_indices) != 1:
                st.error("CSV export requires exactly one selected table.")
            else:
                slice_cfg = st.session_state.get(SS_SLICE_CONFIG, {})
                slice_map: Dict[int, Dict[str, Any]] = {}
                for idx in selected_indices:
                    key = f"{doc_id}|{idx}"
                    cfg = slice_cfg.get(key, {"mode": "table", "row": None, "column": None})
                    slice_map[idx] = cfg

                ev_before = len(engine.get_events())
                with st.spinner("Generating export..."):
                    output = engine.export_interactive(
                        file_id=doc_id,
                        candidates=candidates,
                        selected_candidate_indices=selected_indices,
                        slice_configs=slice_map,
                        docs_meta=docs,
                        export_format=export_format,
                        include_xlsx=include_xlsx,
                    )
                ev_after = engine.get_events()[ev_before:]
                warn_msgs = [e["message"] for e in ev_after if str(e.get("level")) in ("WARN", "ERROR")]

                filename = "results.csv" if export_format == "csv" else "results.zip"
                mime = "text/csv" if export_format == "csv" else "application/zip"

                st.session_state[SS_INTERACTIVE_EXPORT][doc_id] = {
                    "data": output,
                    "file_name": filename,
                    "mime": mime,
                    "format": export_format,
                    "events": ev_after,
                    "warnings": warn_msgs,
                }

        last = st.session_state[SS_INTERACTIVE_EXPORT].get(doc_id)
        if last:
            for msg in last.get("warnings", []):
                st.warning(msg)

            fmt = str(last.get("format"))
            data = last.get("data", b"")
            fname = str(last.get("file_name"))
            mime = str(last.get("mime"))

            if fmt == "csv":
                with st.expander("CSV Preview", expanded=True):
                    _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=data)
                with st.expander("JSONL Preview", expanded=False):
                    preview = _build_jsonl_preview_from_csv(data, max_lines=50)
                    if preview:
                        st.text(preview)
                    else:
                        st.info("No JSONL preview available.")
            else:
                members = _extract_zip_members(data)
                if "results.csv" in members:
                    with st.expander("CSV Preview (from ZIP)", expanded=True):
                        _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=members["results.csv"])
                if "results.jsonl" in members:
                    with st.expander("JSONL Preview (from ZIP)", expanded=False):
                        try:
                            txt = members["results.jsonl"].decode("utf-8", errors="replace")
                        except Exception:
                            txt = ""
                        lines = txt.splitlines()
                        st.text("\n".join(lines[:50]) + ("\n" if lines else ""))
                if "manifest.json" in members:
                    with st.expander("Manifest Preview (from ZIP)", expanded=False):
                        try:
                            st.json(json.loads(members["manifest.json"].decode("utf-8", errors="replace")))
                        except Exception:
                            st.text(members["manifest.json"].decode("utf-8", errors="replace"))

            st.download_button(
                "Download Export",
                data=data,
                file_name=fname,
                mime=mime,
                use_container_width=True,
            )

    st.divider()
    st.subheader("Batch Directory Extraction")

    directory_path = st.text_input("Directory Path", key="batch_dir_path")

    page_1b = st.number_input(
        "Page (1-based)",
        min_value=1,
        step=1,
        value=1,
        key="batch_page",
    )

    table_index_1b = st.number_input(
        "Table Index on Page (1-based)",
        min_value=1,
        step=1,
        value=1,
        key="batch_table_index",
    )

    slice_mode = st.selectbox(
        "Slice Mode",
        options=["table", "row", "column", "cell"],
        index=0,
        key="batch_slice_mode",
    )

    row_val = None
    col_val = None

    if slice_mode in ("row", "cell"):
        row_val = st.number_input(
            "Row (1-based)",
            min_value=1,
            step=1,
            value=1,
            key="batch_row",
        )

    if slice_mode in ("column", "cell"):
        col_val = st.number_input(
            "Column (1-based)",
            min_value=1,
            step=1,
            value=1,
            key="batch_column",
        )

    export_format_batch = st.selectbox(
        "Export Format",
        options=["csv", "zip"],
        index=0,
        key="batch_export_format",
    )

    include_xlsx_batch = False
    if export_format_batch == "zip":
        include_xlsx_batch = st.checkbox(
            "Include XLSX (if supported)",
            value=False,
            key="batch_include_xlsx",
        )

    if st.button("Run Batch Extraction", use_container_width=True):
        if not directory_path:
            st.error("Provide a valid directory path.")
        else:
            try:
                with st.spinner("Running batch extraction..."):
                    output = engine.batch_extract_directory(
                        directory_path=directory_path,
                        page_1b=int(page_1b),
                        table_index_1b=int(table_index_1b),
                        slice_mode=str(slice_mode),
                        row_1b=(None if row_val is None else int(row_val)),
                        col_1b=(None if col_val is None else int(col_val)),
                        export_format=str(export_format_batch),
                        include_xlsx=bool(include_xlsx_batch),
                    )

                filename = "batch_results.csv" if export_format_batch == "csv" else "batch_results.zip"
                mime = "text/csv" if export_format_batch == "csv" else "application/zip"

                st.session_state[SS_BATCH_EXPORT] = {
                    "data": output,
                    "file_name": filename,
                    "mime": mime,
                    "format": str(export_format_batch),
                }

            except Exception as e:
                st.error(str(e))

    last_batch = st.session_state.get(SS_BATCH_EXPORT)
    if last_batch and isinstance(last_batch, dict) and last_batch.get("data"):
        fmtb = str(last_batch.get("format"))
        datab = last_batch.get("data", b"")
        if fmtb == "csv":
            with st.expander("Batch CSV Preview", expanded=False):
                _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=datab)
            with st.expander("Batch JSONL Preview", expanded=False):
                preview = _build_jsonl_preview_from_csv(datab, max_lines=50)
                if preview:
                    st.text(preview)
                else:
                    st.info("No JSONL preview available.")
        else:
            membersb = _extract_zip_members(datab)
            if "results.csv" in membersb:
                with st.expander("Batch CSV Preview (from ZIP)", expanded=False):
                    _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=membersb["results.csv"])
            if "results.jsonl" in membersb:
                with st.expander("Batch JSONL Preview (from ZIP)", expanded=False):
                    try:
                        txt = membersb["results.jsonl"].decode("utf-8", errors="replace")
                    except Exception:
                        txt = ""
                    lines = txt.splitlines()
                    st.text("\n".join(lines[:50]) + ("\n" if lines else ""))

        st.download_button(
            "Download Batch Result",
            data=datab,
            file_name=str(last_batch.get("file_name")),
            mime=str(last_batch.get("mime")),
            use_container_width=True,
        )