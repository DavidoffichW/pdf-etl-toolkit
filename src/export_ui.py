from __future__ import annotations

import csv
import json
import zipfile
from io import BytesIO, StringIO
from typing import Any, Dict, List, Tuple

import streamlit as st

import state
from engine import BatchLimits


def _collect_selected(doc_id: str) -> List[int]:
    indices: List[int] = []
    for key, selected in st.session_state[state.SS_CONFIRMED].items():
        if selected and key.startswith(doc_id + "|"):
            try:
                indices.append(int(key.split("|")[1]))
            except (IndexError, ValueError):
                continue
    return sorted(set(indices))


def _parse_csv_preview(csv_bytes: bytes, *, max_rows: int) -> Tuple[List[str], List[List[str]]]:
    try:
        reader = csv.reader(StringIO(csv_bytes.decode("utf-8")))
    except (UnicodeDecodeError, csv.Error):
        return [], []
    rows: List[List[str]] = []
    headers: List[str] = []
    for index, row in enumerate(reader):
        if index == 0:
            headers = list(row)
        elif len(rows) < max_rows:
            rows.append(list(row))
        else:
            break
    return headers, rows


def _build_jsonl_preview_from_csv(csv_bytes: bytes, *, max_lines: int) -> str:
    headers, rows = _parse_csv_preview(csv_bytes, max_rows=max_lines)
    lines = [
        json.dumps(
            {header: (row[index] if index < len(row) else "") for index, header in enumerate(headers)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for row in rows
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _extract_zip_members(zip_bytes: bytes) -> Dict[str, bytes]:
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}
    except (OSError, KeyError, zipfile.BadZipFile):
        return {}


def _render_tabular_preview(*, label: str, csv_bytes: bytes) -> None:
    headers, rows = _parse_csv_preview(csv_bytes, max_rows=200)
    if not headers:
        st.info("No CSV preview available.")
        return
    st.caption(label)
    st.dataframe(
        [
            {header: (row[index] if index < len(row) else "") for index, header in enumerate(headers)}
            for row in rows
        ],
        use_container_width=True,
        height=280,
    )


def render_interactive_export_panel(engine: Any) -> None:
    docs = state.get_docs()
    if not docs:
        st.info("Upload a PDF to enable interactive export.")
        return
    active = state.get_active_doc()
    if active is None:
        st.info("Select a document.")
        return

    doc_id = active["doc_id"]
    candidates = st.session_state[state.SS_DETECTIONS].get(doc_id)
    if not candidates:
        st.info("Run detection before interactive export.")
        return

    st.subheader("Interactive Export")
    selected_indices = _collect_selected(doc_id)
    export_format = st.selectbox(
        "Export Format",
        options=["csv", "zip"],
        index=0,
        key="interactive_export_format",
    )
    include_xlsx = bool(
        export_format == "zip"
        and st.checkbox(
            "Include XLSX (if supported)",
            value=False,
            key="interactive_include_xlsx",
        )
    )
    signature = {
        "selected": selected_indices,
        "slices": {
            str(index): st.session_state[state.SS_SLICE_CONFIG].get(
                f"{doc_id}|{index}", {"mode": "table", "row": None, "column": None}
            )
            for index in selected_indices
        },
        "format": export_format,
        "include_xlsx": include_xlsx,
    }

    if not selected_indices:
        st.info("Select at least one detected table.")
    elif export_format == "csv" and len(selected_indices) != 1:
        st.warning("CSV export supports exactly one selected table. Use ZIP for multiple tables.")
    elif st.button("Generate Export", use_container_width=True):
        slice_map = {
            index: st.session_state[state.SS_SLICE_CONFIG].get(
                f"{doc_id}|{index}", {"mode": "table", "row": None, "column": None}
            )
            for index in selected_indices
        }
        event_start = len(engine.get_events())
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
        events = engine.get_events()[event_start:]
        st.session_state[state.SS_INTERACTIVE_EXPORT][doc_id] = {
            "data": output,
            "file_name": "results.csv" if export_format == "csv" else "results.zip",
            "mime": "text/csv" if export_format == "csv" else "application/zip",
            "format": export_format,
            "events": events,
            "signature": signature,
        }

    last = st.session_state[state.SS_INTERACTIVE_EXPORT].get(doc_id)
    if not last or last.get("signature") != signature:
        return
    for event in last.get("events", []):
        if event.get("level") in {"WARN", "ERROR"}:
            st.warning(event.get("message", "Export warning"))

    data = last["data"]
    if last["format"] == "csv":
        with st.expander("CSV Preview", expanded=True):
            _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=data)
        with st.expander("JSONL Preview", expanded=False):
            st.text(_build_jsonl_preview_from_csv(data, max_lines=50))
    else:
        members = _extract_zip_members(data)
        if "results.csv" in members:
            with st.expander("CSV Preview (from ZIP)", expanded=True):
                _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=members["results.csv"])
        if "results.jsonl" in members:
            with st.expander("JSONL Preview (from ZIP)", expanded=False):
                st.text("\n".join(members["results.jsonl"].decode("utf-8").splitlines()[:50]))
        if "manifest.json" in members:
            with st.expander("Manifest Preview (from ZIP)", expanded=False):
                st.json(json.loads(members["manifest.json"].decode("utf-8")))

    st.download_button(
        "Download Export",
        data=data,
        file_name=last["file_name"],
        mime=last["mime"],
        use_container_width=True,
    )


def render_batch_export_panel(engine: Any) -> None:
    st.subheader("Batch Directory Extraction")
    limits = BatchLimits()
    st.caption(
        "Trusted local use only. Non-recursive limits: "
        f"{limits.max_files} PDFs, {limits.max_file_bytes // (1024 * 1024)} MiB per file, "
        f"{limits.max_total_bytes // (1024 * 1024)} MiB total, {limits.max_pages} pages."
    )
    directory_path = st.text_input("Directory Path", key="batch_dir_path")
    page_1b = st.number_input("Page (1-based)", min_value=1, value=1, key="batch_page")
    table_index_1b = st.number_input(
        "Table Index on Page (1-based)", min_value=1, value=1, key="batch_table_index"
    )
    slice_mode = st.selectbox(
        "Slice Mode", ["table", "row", "column", "cell"], key="batch_slice_mode"
    )
    row_value = (
        st.number_input("Row (1-based)", min_value=1, value=1, key="batch_row")
        if slice_mode in {"row", "cell"}
        else None
    )
    column_value = (
        st.number_input("Column (1-based)", min_value=1, value=1, key="batch_column")
        if slice_mode in {"column", "cell"}
        else None
    )
    export_format = st.selectbox(
        "Batch Export Format", ["csv", "zip"], key="batch_export_format"
    )
    include_xlsx = bool(
        export_format == "zip"
        and st.checkbox("Include XLSX (if supported)", key="batch_include_xlsx")
    )
    signature = {
        "directory": directory_path,
        "page": int(page_1b),
        "table": int(table_index_1b),
        "slice": slice_mode,
        "row": row_value,
        "column": column_value,
        "format": export_format,
        "include_xlsx": include_xlsx,
    }

    if st.button("Run Batch Extraction", use_container_width=True):
        state.clear_batch_export()
        if not directory_path:
            st.error("Provide a directory path.")
        else:
            try:
                with st.spinner("Running batch extraction..."):
                    result = engine.batch_extract_directory_result(
                        directory_path=directory_path,
                        page_1b=int(page_1b),
                        table_index_1b=int(table_index_1b),
                        slice_mode=slice_mode,
                        row_1b=(None if row_value is None else int(row_value)),
                        col_1b=(None if column_value is None else int(column_value)),
                        export_format=export_format,
                        include_xlsx=include_xlsx,
                        limits=limits,
                    )
                st.session_state[state.SS_BATCH_EXPORT] = {
                    "data": result.data,
                    "report": result.report,
                    "files": [item.__dict__ for item in result.files],
                    "successes": result.success_count,
                    "failures": result.failure_count,
                    "file_name": (
                        "batch_results.csv" if export_format == "csv" else "batch_results.zip"
                    ),
                    "mime": "text/csv" if export_format == "csv" else "application/zip",
                    "format": export_format,
                    "signature": signature,
                }
            except Exception as exc:
                st.error(str(exc))

    last = st.session_state.get(state.SS_BATCH_EXPORT, {})
    if not last or last.get("signature") != signature:
        return
    if last["failures"]:
        st.warning(f"Batch completed with {last['successes']} success(es) and {last['failures']} failure(s).")
    else:
        st.success(f"Batch completed with {last['successes']} successful file(s).")
    st.dataframe(last["files"], use_container_width=True)
    if last["format"] == "csv":
        with st.expander("Batch CSV Preview", expanded=False):
            _render_tabular_preview(label="Top rows (up to 200)", csv_bytes=last["data"])
    st.download_button(
        "Download Batch Result",
        data=last["data"],
        file_name=last["file_name"],
        mime=last["mime"],
        use_container_width=True,
    )
    st.download_button(
        "Download Batch Report",
        data=last["report"],
        file_name="batch_report.json",
        mime="application/json",
        use_container_width=True,
    )


def render_export_panel(engine: Any) -> None:
    """Compatibility wrapper used by integrations that expect the old function."""
    render_interactive_export_panel(engine)
    st.divider()
    render_batch_export_panel(engine)
