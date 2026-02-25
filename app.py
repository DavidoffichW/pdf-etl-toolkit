import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import streamlit as st

from capabilities import detect_capabilities
from engine import Engine
from runplan import build_run_plan, run_plan_to_dict

import state
import workspace
import preview
import ordering
import detection_ui
import export_ui


st.set_page_config(page_title="pdf-etl-toolkit", layout="wide")

caps_raw = detect_capabilities()
caps = state.caps_from_detect(caps_raw)
plan = build_run_plan(caps_raw)
plan_dict = run_plan_to_dict(plan)

state.init_state(caps_raw=caps_raw, caps=caps, plan=plan, plan_dict=plan_dict)

engine = Engine(plan)

st.title("pdf-etl-toolkit")

with st.expander("Environment & Capabilities", expanded=False):
    st.json(plan_dict)

tab_merge, tab_etl = st.tabs(["PDF Merger", "PDF → CSV ETL"])


def _active_doc_selector(docs_meta, key_suffix: str):
    if not docs_meta:
        return None

    active_doc_id = state.get_active_doc_id()
    ids = [d["doc_id"] for d in docs_meta]

    if active_doc_id not in ids:
        state.set_active_doc_id(ids[0])
        active_doc_id = ids[0]

    picked = st.radio(
        "Active document",
        options=ids,
        index=ids.index(active_doc_id),
        format_func=lambda x: next(dd["filename"] for dd in docs_meta if dd["doc_id"] == x),
        key=f"active_doc_radio_{key_suffix}",
    )

    if picked != active_doc_id:
        state.set_active_doc_id(picked)
        return True

    return False


with tab_merge:
    left, right = st.columns([1, 2])
    state_changed = False

    with left:
        st.subheader("Workspace")

        uploader_key = f"uploader_widget_{state.get_uploader_token()}"
        uploaded = st.file_uploader(
            "Add PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            key=uploader_key,
        )

        ingest_changed = workspace.ingest_uploaded(engine, uploaded)
        if ingest_changed:
            state.bump_uploader_token()
            state_changed = True

        docs = state.get_docs()
        if not docs:
            st.info("Upload one or more PDFs to start.")
        else:
            changed = _active_doc_selector(docs, "merge")
            if changed:
                state_changed = True

            st.divider()
            st.subheader("Document Order")

            current_order = state.get_order()
            new_order = ordering.render_drag_drop_order(
                docs=docs,
                current_order=current_order,
                key="doc_sortable_merge_tab",
            )
            if new_order is not None:
                if workspace.apply_order(new_order):
                    state_changed = True

            st.divider()
            st.subheader("Documents")

            for d in docs:
                doc_id = d["doc_id"]
                c1, c2, c3, c4 = st.columns([6, 1, 1, 2])

                with c1:
                    st.write(f"{d['filename']} ({int(d['page_count'])}p)")
                with c2:
                    if st.button("↑", key=f"up_{doc_id}", use_container_width=True):
                        if workspace.move_up(doc_id):
                            state_changed = True
                with c3:
                    if st.button("↓", key=f"dn_{doc_id}", use_container_width=True):
                        if workspace.move_down(doc_id):
                            state_changed = True
                with c4:
                    if st.button("Remove", key=f"rm_{doc_id}", use_container_width=True):
                        if workspace.remove_doc(doc_id):
                            state_changed = True

            st.divider()
            st.subheader("Page Operations")

            active_doc = state.get_active_doc()
            if active_doc is not None:
                pc = int(active_doc["page_count"])
                if pc <= 0:
                    st.info("Active document has no pages.")
                else:
                    r1, r2 = st.columns(2)
                    with r1:
                        start_page = st.number_input(
                            "Start page",
                            min_value=1,
                            max_value=pc,
                            value=1,
                            step=1,
                            key="op_start_page_merge",
                        )
                    with r2:
                        end_page = st.number_input(
                            "End page",
                            min_value=1,
                            max_value=pc,
                            value=min(pc, int(start_page)),
                            step=1,
                            key="op_end_page_merge",
                        )

                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button(
                            "Extract range as new document",
                            use_container_width=True,
                            key="extract_range_btn",
                        ):
                            if workspace.extract_range_to_new_doc(
                                engine,
                                active_doc["doc_id"],
                                int(start_page),
                                int(end_page),
                            ):
                                state_changed = True
                    with c2:
                        if st.button(
                            "Delete range in active document",
                            use_container_width=True,
                            key="delete_range_btn",
                        ):
                            if workspace.delete_range_in_doc(
                                engine,
                                active_doc["doc_id"],
                                int(start_page),
                                int(end_page),
                            ):
                                state_changed = True

            st.divider()
            st.subheader("Merged Output")

            merged = state.get_merged_bytes()
            if merged:
                st.download_button(
                    "Download merged PDF",
                    data=merged,
                    file_name="merged.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.info("Merged output will appear once at least one PDF is ingested.")

    if state_changed:
        workspace.rebuild_merged()
        st.rerun()

    with right:
        st.subheader("Preview")

        docs = state.get_docs()
        if not docs:
            st.info("Upload PDFs to enable preview.")
        else:
            mode = st.radio(
                "Preview mode",
                options=["Active document", "Merged"],
                index=0,
                horizontal=True,
                key="preview_mode_merge_tab",
            )
            preview.render_preview(mode=mode, key_suffix="merge")


with tab_etl:
    left, right = st.columns([1, 2])

    with left:
        st.subheader("PDF → CSV ETL")

        docs = state.get_docs()
        if not docs:
            st.info("Upload PDFs in the PDF Merger tab to start.")
        else:
            changed = _active_doc_selector(docs, "etl")
            if changed:
                st.rerun()

            st.divider()
            detection_ui.render_detection_panel(engine)

            st.divider()
            export_ui.render_export_panel(engine)

    with right:
        st.subheader("Preview")

        docs = state.get_docs()
        if not docs:
            st.info("Upload PDFs to enable preview.")
        else:
            mode = st.radio(
                "Preview mode",
                options=["Active document", "Merged"],
                index=0,
                horizontal=True,
                key="preview_mode_etl_tab",
            )
            preview.render_preview(mode=mode, key_suffix="etl")