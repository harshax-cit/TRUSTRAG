"""
highlight.py – Render a PDF page with a highlighted bbox.

Returns a PIL Image or bytes (PNG) so it can be displayed in Streamlit.
"""

from __future__ import annotations

import io
import json
from typing import Optional, Union

import pymupdf as fitz
from PIL import Image


HIGHLIGHT_COLOR = (1.0, 0.9, 0.0)   # yellow, RGB 0-1
HIGHLIGHT_ALPHA = 0.4
RENDER_DPI = 150


def render_page_with_highlight(
    pdf_path: str,
    page_num: int,          # 1-indexed
    bbox: Optional[Union[list, str]] = None,
    dpi: int = RENDER_DPI,
    highlight_color: tuple = HIGHLIGHT_COLOR,
) -> bytes:
    """
    Render a PDF page to PNG bytes with an optional highlighted rectangle.

    Args:
        pdf_path:  Absolute path to the PDF.
        page_num:  1-indexed page number.
        bbox:      [x0, y0, x1, y1] in PDF points, or JSON string, or None.
        dpi:       Render resolution.
        highlight_color: RGB tuple (0-1 each).

    Returns:
        PNG bytes of the rendered page.
    """
    if isinstance(bbox, str):
        try:
            bbox = json.loads(bbox)
        except Exception:
            bbox = None

    doc = fitz.open(pdf_path)
    page_idx = page_num - 1
    if page_idx < 0 or page_idx >= len(doc):
        doc.close()
        raise ValueError(f"Page {page_num} out of range (doc has {len(doc)} pages)")

    page = doc[page_idx]

    if bbox and len(bbox) == 4:
        x0, y0, x1, y1 = bbox
        rect = fitz.Rect(x0, y0, x1, y1)
        # Draw semi-transparent highlight
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=highlight_color)
        annot.set_opacity(HIGHLIGHT_ALPHA)
        annot.update()

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def render_page_pil(
    pdf_path: str,
    page_num: int,
    bbox: Optional[Union[list, str]] = None,
    dpi: int = RENDER_DPI,
) -> Image.Image:
    """Return a PIL Image instead of bytes."""
    png_bytes = render_page_with_highlight(pdf_path, page_num, bbox, dpi)
    return Image.open(io.BytesIO(png_bytes))


def get_page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    return n
