from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

import state
from detection_ui import SS_SLICE_CONFIG


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


def render_export_panel(engine: Any) -> None:
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
    if not selected_indices:
        st.info("Select at least one detected table.")
    else:
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

        if export_format == "csv" and len(selected_indices) != 1:
            st.warning("CSV export supports exactly one selected table. Use ZIP for multi-table export.")

        if st.button("Export Selected Tables", use_container_width=True):
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
                for msg in warn_msgs:
                    st.warning(msg)

                filename = "results.csv" if export_format == "csv" else "results.zip"
                mime = "text/csv" if export_format == "csv" else "application/zip"
                st.download_button(
                    "Download",
                    data=output,
                    file_name=filename,
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
                st.download_button(
                    "Download Batch Result",
                    data=output,
                    file_name=filename,
                    mime=mime,
                    use_container_width=True,
                )
            except Exception as e:
                st.error(str(e))          
