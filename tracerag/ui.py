"""
tracerag/ui.py - Shared design system for TraceRAG.

Provides apply_enterprise_theme() and all reusable components.
Every role uses these same primitives - only content changes.
"""

from __future__ import annotations
import streamlit as st

# CSS and theme
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #111827;
    background-color: #f9fafb;
    -webkit-font-smoothing: antialiased;
}
.stApp { background-color: #f9fafb !important; }

.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 1200px !important;
}
</style>
"""


def apply_enterprise_theme() -> None:
    """Legacy theme function - new UI uses ui.theme.inject_theme()"""
    st.markdown(_CSS, unsafe_allow_html=True)


def offline_banner() -> None:
    pass  # removed per design requirements


def render_page_header(title: str, description: str = "", icon: str = "") -> None:
    """Wrapper for new page_header component"""
    try:
        from ui.components import page_header
        page_header(title, description)
    except ImportError:
        st.markdown(f"## {icon} {title}" if icon else f"## {title}")
        if description:
            st.caption(description)
