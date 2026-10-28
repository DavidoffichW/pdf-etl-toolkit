from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from typing import Literal, Tuple

import streamlit as st
import state


def _sha16(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:16]


PREVIEW_CACHE_MAX_ENTRIES = 128


def _has_pdfium() -> bool:
    try:
        import pypdfium2  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _is_heavy_pdf(blob: bytes, page_count: int) -> bool:
    return len(blob) >= 8_000_000 or page_count >= 120


def _img_html(*, mime: str, img_bytes: bytes, margin_px: int, zoom: float) -> None:
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    html = f"""
    <div style="width:100%; height:100%; overflow:auto;">
      <div style="padding:{int(margin_px)}px; display:flex; justify-content:center;">
        <img
          src="data:{mime};base64,{b64}"
          style="
            transform:scale({float(zoom)});
            transform-origin:top center;
            display:block;
            height:auto;
          "
        />
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _iframe_pdf(*, pdf_bytes: bytes, page_1b: int, height_px: int, key_suffix: str) -> None:
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f"""
    <div style="height:{int(height_px)}px; width:100%;">
      <iframe
        src="data:application/pdf;base64,{b64}#page={int(page_1b)}"
        width="100%"
        height="100%"
        style="border:none;"
      ></iframe>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=PREVIEW_CACHE_MAX_ENTRIES)
def _render_page_image(
    pdf_sha16: str,
    page_index: int,
    sharp: float,
    fmt: str,
    pdf_bytes: bytes,
) -> Tuple[str, bytes]:
    import pypdfium2 as pdfium  # type: ignore

    document = pdfium.PdfDocument(pdf_bytes)
    page = None
    bitmap = None
    image = None
    encoded_image = None
    try:
        if page_index < 0 or page_index >= len(document):
            raise ValueError("preview page index is out of range")
        page = document[page_index]
        bitmap = page.render(scale=float(sharp))
        image = bitmap.to_pil()
        output = BytesIO()
        if fmt.lower() in {"jpg", "jpeg"}:
            encoded_image = image if image.mode == "RGB" else image.convert("RGB")
            encoded_image.save(output, format="JPEG", quality=90)
            return "image/jpeg", output.getvalue()
        image.save(output, format="PNG")
        return "image/png", output.getvalue()
    finally:
        if encoded_image is not None and encoded_image is not image:
            encoded_image.close()
        if image is not None:
            image.close()
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        document.close()


def _single_page_image_viewer(
    *,
    title: str,
    pdf_bytes: bytes,
    page_count: int,
    height_px: int,
    key_suffix: str,
) -> None:
    if not _has_pdfium():
        st.warning("Install pypdfium2 and Pillow for image preview.")
        return

    st.markdown(f"### {title}")
    pdf_id = _sha16(pdf_bytes)

    zoom_key = f"pv_zoom_{key_suffix}"
    margin_key = f"pv_margin_{key_suffix}"
    page_key = f"pv_page_{key_suffix}"

    if zoom_key not in st.session_state:
        st.session_state[zoom_key] = 1.0
    if margin_key not in st.session_state:
        st.session_state[margin_key] = 24
    if page_key not in st.session_state:
        st.session_state[page_key] = 1

    nav_col1, nav_col2, nav_col3, render_col1, render_col2, render_col3 = st.columns(
        [0.6, 0.6, 1.2, 1.5, 1.5, 0.8]
    )

    def _prev() -> None:
        st.session_state[page_key] = max(1, int(st.session_state[page_key]) - 1)

    def _next() -> None:
        st.session_state[page_key] = min(page_count, int(st.session_state[page_key]) + 1)

    with nav_col1:
        st.button("◀", key=f"pv_prev_{key_suffix}", on_click=_prev)

    with nav_col2:
        st.button("▶", key=f"pv_next_{key_suffix}", on_click=_next)

    with nav_col3:
        st.number_input(
            "Page",
            min_value=1,
            max_value=page_count,
            value=int(st.session_state[page_key]),
            step=1,
            label_visibility="collapsed",
            key=page_key,
        )

    with render_col1:
        st.slider(
            "Zoom",
            0.5,
            3.0,
            float(st.session_state[zoom_key]),
            0.1,
            label_visibility="collapsed",
            key=zoom_key,
        )

    with render_col2:
        st.slider(
            "Margins",
            0,
            160,
            int(st.session_state[margin_key]),
            4,
            label_visibility="collapsed",
            key=margin_key,
        )

    with render_col3:
        if st.button("Fit", key=f"pv_fit_{key_suffix}"):
            st.session_state[zoom_key] = 1.0
            st.session_state[margin_key] = 24
            st.rerun()

    sharp = st.select_slider(
        "Sharpness",
        options=[0.75, 1.0, 1.25, 1.5, 2.0],
        value=1.0,
        key=f"pv_sharp_{key_suffix}",
    )
    fmt = st.selectbox("Format", ["jpg", "png"], key=f"pv_fmt_{key_suffix}")

    page_1b = int(st.session_state[page_key])
    st.caption(
        f"Page {page_1b}/{page_count} | Zoom {float(st.session_state[zoom_key]):.1f}x | Sharp {sharp}x"
    )

    try:
        mime, img = _render_page_image(
            pdf_sha16=pdf_id,
            page_index=page_1b - 1,
            sharp=float(sharp),
            fmt=fmt,
            pdf_bytes=pdf_bytes,
        )
    except Exception as exc:
        st.error(f"Image preview failed: {exc}")
        return

    with st.container(height=height_px, border=True):
        _img_html(
            mime=mime,
            img_bytes=img,
            margin_px=int(st.session_state[margin_key]),
            zoom=float(st.session_state[zoom_key]),
        )
        
def _pdf_iframe_viewer(
    *,
    title: str,
    pdf_bytes: bytes,
    page_count: int,
    height_px: int,
    key_suffix: str,
) -> None:

    st.markdown(f"### {title}")

    page_1b = st.number_input(
        "Go to page",
        1,
        page_count,
        1,
        key=f"pv_iframe_jump_{key_suffix}",
    )

    with st.container(height=height_px, border=True):
        _iframe_pdf(
            pdf_bytes=pdf_bytes,
            page_1b=page_1b,
            height_px=height_px - 10,
            key_suffix=key_suffix,
        )


def render_preview(*, mode: Literal["Active document", "Merged"], key_suffix: str) -> None:

    docs = state.get_docs()
    if not docs:
        st.info("No documents loaded.")
        return

    if mode == "Active document":
        active = state.get_active_doc()
        if active is None:
            st.info("No active document.")
            return
        blob = state.get_doc_bytes(active["doc_id"])
        page_count = int(active["page_count"])
        title = "Active document preview"
    else:
        blob = state.get_merged_bytes()
        if not blob:
            st.info("No merged document available.")
            return
        page_count = len(state.get_page_map())
        title = "Merged preview"

    if page_count <= 0:
        st.info("Document has no pages.")
        return

    height_px = 720

    renderer = st.radio(
        "Preview renderer",
        ["Auto", "PDF (iframe)", "Images (single-page)"],
        horizontal=True,
        key=f"pv_renderer_{key_suffix}",
    )

    if renderer == "Auto":
        renderer = "Images (single-page)" if _is_heavy_pdf(blob, page_count) else "PDF (iframe)"

    if renderer == "PDF (iframe)":
        _pdf_iframe_viewer(
            title=title,
            pdf_bytes=blob,
            page_count=page_count,
            height_px=height_px,
            key_suffix=f"{key_suffix}_pdf",
        )
    else:
        _single_page_image_viewer(
            title=title,
            pdf_bytes=blob,
            page_count=page_count,
            height_px=height_px,
            key_suffix=f"{key_suffix}_img",
        )
