from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


def _try_sortables() -> Tuple[bool, Any]:
    try:
        from streamlit_sortables import sort_items  # type: ignore
        return True, sort_items
    except Exception:
        return False, None


def render_drag_drop_order(
    *,
    docs: List[Dict[str, Any]],
    current_order: List[str],
    key: str,
) -> Optional[List[str]]:
    if not docs or not current_order:
        return None

    ok, sort_items = _try_sortables()
    if not ok:
        st.info("Drag-and-drop ordering is unavailable. Install: pip install streamlit-sortables")
        return None

    by_id = {d["doc_id"]: d for d in docs}
    ordered_docs = [by_id[x] for x in current_order if x in by_id]

    items = [{"doc_id": d["doc_id"], "label": f"{d['filename']} ({int(d['page_count'])}p)"} for d in ordered_docs]

    css = """
    .sortable-component { border: 1px solid rgba(49, 51, 63, 0.2); border-radius: 10px; padding: 8px; }
    .sortable-container { background: transparent; }
    .sortable-item { border: 1px solid rgba(49, 51, 63, 0.15); border-radius: 10px; padding: 8px 10px; margin: 6px 0; }
    .sortable-item:hover { border-color: rgba(49, 51, 63, 0.35); }
    """

    out = sort_items(items, multi_containers=False, custom_style=css, key=key)

    if not isinstance(out, list) or not out:
        return None

    new_order: List[str] = []
    for x in out:
        if isinstance(x, dict) and "doc_id" in x:
            new_order.append(str(x["doc_id"]))

    if not new_order:
        return None

    if new_order == current_order:
        return None

    return new_order