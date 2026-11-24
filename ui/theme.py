"""
ui/theme.py – Design tokens and CSS injection for TraceRAG.
Reads ui/styles.css once and injects via st.markdown.
"""

from __future__ import annotations
from pathlib import Path
import streamlit as st

# ── Design tokens (Python-side, for computed styles) ─────────────────────────
NAVY    = "#0B1F33"
NAVY2   = "#16324F"
TEAL    = "#0F7C7E"
TEAL_HV = "#0B6567"
AMBER   = "#F5B700"
BG      = "#F4F7FA"
CARD    = "#FFFFFF"
BORDER  = "#DDE5EC"
MUTED   = "#5B6878"
TEXT    = "#0B1F33"

STATUS_COLORS = {
    "answer":   {"bg": "#E8F5EC", "text": "#1D6B43", "label": "Verified"},
    "conflict": {"bg": "#FFF4D1", "text": "#6B4E00", "label": "Conflict"},
    "refuse":   {"bg": "#FBE9E7", "text": "#9A2B1F", "label": "Not found"},
}

_CSS_CACHE: str | None = None


def _load_css() -> str:
    global _CSS_CACHE
    if _CSS_CACHE is None:
        css_path = Path(__file__).parent / "styles.css"
        if css_path.exists():
            _CSS_CACHE = f"<style>{css_path.read_text()}</style>"
        else:
            _CSS_CACHE = ""
    return _CSS_CACHE


def inject_theme() -> None:
    """Inject master CSS once per page render."""
    st.markdown(_load_css(), unsafe_allow_html=True)
