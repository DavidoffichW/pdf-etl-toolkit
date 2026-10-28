from __future__ import annotations

from io import BytesIO

import pypdfium2
import pytest
from PIL import Image

import preview


def _render(pdf: bytes, *, page: int = 0, sharp: float = 1.0, fmt: str = "png"):
    preview._render_page_image.clear()
    return preview._render_page_image(
        pdf_sha16=f"fixture-{page}-{sharp}-{fmt}",
        page_index=page,
        sharp=sharp,
        fmt=fmt,
        pdf_bytes=pdf,
    )


def test_pdfium_renders_png_jpeg_pages_and_scale(plain_pdf):
    png_mime, png = _render(plain_pdf, page=0, sharp=1.0, fmt="png")
    jpeg_mime, jpeg = _render(plain_pdf, page=1, sharp=2.0, fmt="jpg")
    assert png_mime == "image/png"
    assert jpeg_mime == "image/jpeg"
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert jpeg.startswith(b"\xff\xd8")
    with Image.open(BytesIO(png)) as image:
        assert image.size == (420, 320)
    with Image.open(BytesIO(jpeg)) as image:
        assert image.size == (840, 640)
    assert png != _render(plain_pdf, page=1, sharp=1.0, fmt="png")[1]


def test_pdfium_invalid_page_is_controlled_and_document_closes(plain_pdf, monkeypatch):
    closed = {"document": False}
    original = pypdfium2.PdfDocument

    class TrackedDocument:
        def __init__(self, data):
            self._document = original(data)

        def __len__(self):
            return len(self._document)

        def __getitem__(self, index):
            return self._document[index]

        def close(self):
            closed["document"] = True
            self._document.close()

    monkeypatch.setattr(pypdfium2, "PdfDocument", TrackedDocument)
    with pytest.raises(ValueError, match="out of range"):
        _render(plain_pdf, page=99)
    assert closed["document"] is True


def test_pdfium_page_bitmap_image_and_document_are_closed(monkeypatch):
    closed = {"document": False, "page": False, "bitmap": False, "image": False}
    observed = {"scale": None}

    class FakeImage:
        mode = "RGB"

        def save(self, destination, *, format, **kwargs):
            destination.write(b"encoded-image")

        def close(self):
            closed["image"] = True

    class FakeBitmap:
        def to_pil(self):
            return FakeImage()

        def close(self):
            closed["bitmap"] = True

    class FakePage:
        def render(self, *, scale):
            observed["scale"] = scale
            return FakeBitmap()

        def close(self):
            closed["page"] = True

    class FakeDocument:
        def __init__(self, data):
            pass

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return FakePage()

        def close(self):
            closed["document"] = True

    monkeypatch.setattr(pypdfium2, "PdfDocument", FakeDocument)
    mime, data = _render(b"synthetic", sharp=1.25, fmt="png")
    assert (mime, data) == ("image/png", b"encoded-image")
    assert observed["scale"] == 1.25
    assert all(closed.values())


def test_preview_cache_bound_is_preserved():
    assert preview.PREVIEW_CACHE_MAX_ENTRIES == 128
