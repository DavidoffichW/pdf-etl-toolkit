from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

import state


SS_SLICE_CONFIG = "slice_config"


def _slice_key(doc_id: str, candidate_index: int) -> str:
    return f"{doc_id}|{candidate_index}"


def _init_slice_state() -> None:
    if SS_SLICE_CONFIG not in st.session_state:
        st.session_state[SS_SLICE_CONFIG] = {}


def render_detection_panel(engine: Any) -> None:
    _init_slice_state()

    docs = state.get_docs()
    if not docs:
        st.info("No documents available.")
        return

    active = state.get_active_doc()
    if active is None:
        st.info("Select a document.")
        return

    if engine.run_plan.tables.status != "OK":
        st.warning(f"Table detection unavailable: {engine.run_plan.tables.reason}")
        return

    doc_id = active["doc_id"]
    blob = state.get_doc_bytes(doc_id)

    st.subheader("Table Detection")

    if st.button("Run Detection", use_container_width=True):
        res = engine.detect_tables(file_id=doc_id, data=blob)
        st.session_state[state.SS_DETECTIONS][doc_id] = res.candidates
        st.rerun()

    candidates = st.session_state[state.SS_DETECTIONS].get(doc_id)
    if not candidates:
        st.info("Run detection to find tables.")
        return

    st.divider()
    st.subheader("Detected Tables")

    confirmed = st.session_state[state.SS_CONFIRMED]
    slice_cfg = st.session_state[SS_SLICE_CONFIG]

    for idx, cand in enumerate(candidates):
        key = _slice_key(doc_id, idx)

        with st.container():
            c1, c2 = st.columns([5, 1])

            with c1:
                st.write(
                    f"Page {cand.page_index + 1} | "
                    f"Rows: {cand.row_count} | Cols: {cand.col_count} | "
                    f"Score: {round(float(cand.score), 3)}"
                )

            with c2:
                selected = confirmed.get(key, False)
                new_val = st.checkbox("Select", value=selected, key=f"select_{key}")
                confirmed[key] = new_val

            if confirmed.get(key, False):
                cfg = slice_cfg.get(key, {"mode": "table", "row": None, "column": None})

                mode = st.selectbox(
                    "Slice Mode",
                    options=["table", "row", "column", "cell"],
                    index=["table", "row", "column", "cell"].index(cfg.get("mode", "table")),
                    key=f"mode_{key}",
                )

                row_val = cfg.get("row")
                col_val = cfg.get("column")

                if mode in ("row", "cell"):
                    row_val = st.number_input(
                        "Row (1-based)",
                        min_value=1,
                        max_value=int(cand.row_count),
                        value=int(row_val) if row_val else 1,
                        step=1,
                        key=f"row_{key}",
                    )
                else:
                    row_val = None

                if mode in ("column", "cell"):
                    col_val = st.number_input(
                        "Column (1-based)",
                        min_value=1,
                        max_value=int(cand.col_count),
                        value=int(col_val) if col_val else 1,
                        step=1,
                        key=f"col_{key}",
                    )
                else:
                    col_val = None

                slice_cfg[key] = {
                    "mode": mode,
                    "row": row_val,
                    "column": col_val,
                }

    st.session_state[state.SS_CONFIRMED] = confirmed
    st.session_state[SS_SLICE_CONFIG] = slice_cfg