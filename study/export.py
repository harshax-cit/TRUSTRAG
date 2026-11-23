"""
study/export.py – Export flashcards to CSV, Anki TSV, and printable PDF.
"""

from __future__ import annotations

import csv
import io
import unicodedata


def _safe(text: str) -> str:
    """Remove characters outside latin-1 range so Helvetica renders them."""
    # Normalise (e.g. decompose accented chars), then keep only latin-1
    normalised = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in normalised if ord(c) < 256)


def to_csv(cards: list[dict]) -> bytes:
    """Return UTF-8 CSV bytes."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id", "type", "topic_id", "front", "back",
        "doc", "page", "difficulty", "verified",
    ])
    writer.writeheader()
    for c in cards:
        writer.writerow({k: c.get(k, "") for k in writer.fieldnames})
    return buf.getvalue().encode("utf-8")


def to_anki_tsv(cards: list[dict]) -> bytes:
    """
    Anki-compatible TSV: front TAB back TAB tags TAB source
    """
    buf = io.StringIO()
    for c in cards:
        tags   = f"{c.get('type','')}::{c.get('topic_id','')}::{c.get('difficulty','')}"
        source = f"{c.get('doc','')} p.{c.get('page','')}"
        front  = c.get("front", "").replace("\t", " ")
        back   = c.get("back",  "").replace("\t", " ")
        buf.write(f"{front}\t{back}\t{tags}\t{source}\n")
    return buf.getvalue().encode("utf-8")


def to_pdf(cards: list[dict], title: str = "Flashcards") -> bytes:
    """Generate a printable PDF of flashcards using fpdf2."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        raise RuntimeError("fpdf2 is required: pip install fpdf2")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _safe(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(4)

    for i, card in enumerate(cards):
        card_type = card.get("type", "").upper()
        doc_ref   = f"{card.get('doc','')[:30]} p.{card.get('page','')}"
        label     = _safe(f"#{i+1} [{card_type}] {doc_ref}")

        # Header row
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(220, 235, 255)
        pdf.cell(0, 6, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)

        # Front
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(255, 255, 255)
        pdf.multi_cell(0, 6, _safe(f"Q: {card.get('front', '')}"),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Back
        pdf.set_font("Helvetica", "", 10)
        pdf.set_fill_color(240, 255, 240)
        pdf.multi_cell(0, 6, _safe(f"A: {card.get('back', '')}"),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Verification status
        verified = card.get("verified", True)
        mark = "Verified" if verified else "UNVERIFIED - check source"
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(0, 128, 0) if verified else pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 5, mark, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    return bytes(pdf.output())
