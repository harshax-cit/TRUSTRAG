"""
tracerag/ui.py – Master Design System for TraceRAG Enterprise.

One professional design for all six roles.
Roles share the same layout, typography, colors, and components.
Only content and permissions change per role.

Color palette:
  Sidebar background  : #0f2318  (deep forest green)
  Sidebar active      : #1a3d2b
  Primary button      : #16a34a  (green-600)
  Primary hover       : #15803d  (green-700)
  Workspace bg        : #f9fafb  (gray-50)
  Card bg             : #ffffff
  Border              : #e5e7eb  (gray-200)
  Text primary        : #111827  (gray-900)
  Text secondary      : #6b7280  (gray-500)
  Text muted          : #9ca3af  (gray-400)
  Success             : #16a34a
  Warning             : #d97706
  Danger              : #dc2626
  Info                : #2563eb
"""

from __future__ import annotations
import streamlit as st

# ── Design tokens ─────────────────────────────────────────────────────────────
COLORS = {
    "sidebar_bg":      "#0f2318",
    "sidebar_active":  "#1a3d2b",
    "sidebar_border":  "#1e3a28",
    "sidebar_text":    "#cbd5e1",
    "sidebar_text_hi": "#ffffff",
    "primary":         "#16a34a",
    "primary_dark":    "#15803d",
    "workspace_bg":    "#f9fafb",
    "card_bg":         "#ffffff",
    "border":          "#e5e7eb",
    "border_light":    "#f3f4f6",
    "text":            "#111827",
    "text_secondary":  "#6b7280",
    "text_muted":      "#9ca3af",
    "success_bg":      "#f0fdf4",
    "success_text":    "#15803d",
    "success_border":  "#bbf7d0",
    "warn_bg":         "#fffbeb",
    "warn_text":       "#b45309",
    "warn_border":     "#fde68a",
    "danger_bg":       "#fef2f2",
    "danger_text":     "#b91c1c",
    "danger_border":   "#fecaca",
    "info_bg":         "#eff6ff",
    "info_text":       "#1d4ed8",
    "info_border":     "#bfdbfe",
}

MASTER_CSS = """
<style>
/* ── Fonts ─────────────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #111827;
    background-color: #f9fafb;
    -webkit-font-smoothing: antialiased;
}

/* ── App shell ─────────────────────────────────────────────────────────────── */
.stApp {
    background-color: #f9fafb !important;
}

/* Remove default Streamlit padding */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 1200px !important;
}

/* ── Sidebar ───────────────────────────────────��───────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #0f2318 !important;
    border-right: 1px solid #1e3a28 !important;
    min-width: 240px !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding: 1rem 0.75rem !important;
}
[data-testid="stSidebar"] * {
    color: #cbd5e1 !important;
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] strong {
    color: #ffffff !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio > label {
    color: #94a3b8 !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}
/* Sidebar radio active state */
[data-testid="stSidebar"] [data-testid="stRadioOptions"] label {
    text-transform: none !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    color: #cbd5e1 !important;
    padding: 0.4rem 0.5rem !important;
    border-radius: 6px !important;
    transition: background 0.1s;
}
[data-testid="stSidebar"] [data-testid="stRadioOptions"] [aria-checked="true"] + label {
    color: #ffffff !important;
    background-color: #1a3d2b !important;
    font-weight: 600 !important;
}
/* Sidebar divider */
[data-testid="stSidebar"] hr {
    border-color: #1e3a28 !important;
    margin: 0.6rem 0 !important;
}
/* Sidebar info/success/error boxes */
[data-testid="stSidebar"] [data-testid="stNotification"] {
    background-color: #1a3d2b !important;
    border-color: #1e3a28 !important;
}

/* ── Buttons ───────────────────────────────────────────────────────────────── */
/* Primary */
div.stButton > button[kind="primary"],
div.stButton > button[data-testid*="primary"] {
    background-color: #16a34a !important;
    color: #ffffff !important;
    border: 1px solid #15803d !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    padding: 0.5rem 1rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
    transition: background-color 0.15s ease !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #15803d !important;
    border-color: #166534 !important;
}

/* Secondary */
div.stButton > button:not([kind="primary"]) {
    background-color: #ffffff !important;
    color: #374151 !important;
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
    transition: all 0.15s ease !important;
}
div.stButton > button:not([kind="primary"]):hover {
    background-color: #f9fafb !important;
    border-color: #9ca3af !important;
}

/* ── Inputs ────────────────────────────────────────────────────────────────── */
.stTextInput input,
.stTextArea textarea,
.stSelectbox select,
.stNumberInput input {
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    font-size: 0.875rem !important;
    color: #111827 !important;
    background-color: #ffffff !important;
    transition: border-color 0.15s ease !important;
}
.stTextInput input:focus,
.stTextArea textarea:focus {
    border-color: #16a34a !important;
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.1) !important;
}
.stTextInput label,
.stTextArea label,
.stSelectbox label,
.stNumberInput label {
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    color: #374151 !important;
    margin-bottom: 0.25rem !important;
}

/* ── Cards ─────────────────────────────────────────────────────────────────── */
.tr-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    transition: box-shadow 0.15s ease;
    margin-bottom: 0.75rem;
}
.tr-card:hover { box-shadow: 0 4px 8px rgba(0,0,0,0.07); }

.tr-card-sm {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}

/* ── Page header ───────────────────────────────────────────────────────────── */
.tr-page-header {
    padding: 0 0 1rem 0;
    border-bottom: 1px solid #e5e7eb;
    margin-bottom: 1.5rem;
}
.tr-page-title {
    font-size: 1.375rem;
    font-weight: 700;
    color: #111827;
    margin: 0 0 0.25rem 0;
}
.tr-page-desc {
    font-size: 0.875rem;
    color: #6b7280;
    margin: 0;
}

/* ── Top navbar ────────────────────────────────────────────────────────────── */
.tr-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0.65rem 1rem;
    margin-bottom: 1.25rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.tr-topbar-left {
    display: flex; align-items: center; gap: 0.75rem;
}
.tr-topbar-title {
    font-weight: 700; font-size: 1rem; color: #111827; margin: 0;
}
.tr-topbar-right {
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 0.8rem; color: #6b7280;
}
.tr-topbar-right strong { color: #111827; }

/* ── Badges ────────────────────────────────────────────────────────────────── */
.tr-badge {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.2rem 0.6rem; border-radius: 9999px;
    font-size: 0.72rem; font-weight: 600; white-space: nowrap;
}
.tr-badge-green {
    background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0;
}
.tr-badge-red {
    background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca;
}
.tr-badge-amber {
    background: #fffbeb; color: #b45309; border: 1px solid #fde68a;
}
.tr-badge-blue {
    background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe;
}
.tr-badge-gray {
    background: #f9fafb; color: #4b5563; border: 1px solid #e5e7eb;
}

/* ── Stat box ──────────────────────────────────────────────────────────────── */
.tr-stat {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 1rem 1.25rem; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.tr-stat-label {
    font-size: 0.72rem; font-weight: 600; color: #9ca3af;
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.4rem;
}
.tr-stat-value {
    font-size: 1.75rem; font-weight: 700; color: #111827; line-height: 1;
}
.tr-stat-sub {
    font-size: 0.75rem; color: #6b7280; margin-top: 0.25rem;
}

/* ── Tables ────────────────────────────────────────────────────────────────── */
.stDataFrame { border: 1px solid #e5e7eb !important; border-radius: 8px !important; }
.stDataFrame thead th {
    background-color: #f9fafb !important; color: #374151 !important;
    font-weight: 600 !important; font-size: 0.8rem !important;
}
.stDataFrame tbody tr:hover { background-color: #f9fafb !important; }

/* ── Tabs ──────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px; border-bottom: 1px solid #e5e7eb; background: transparent;
}
.stTabs [data-baseweb="tab"] {
    padding: 0.5rem 1rem; border-radius: 6px 6px 0 0;
    font-size: 0.875rem; font-weight: 500; color: #6b7280;
    background: transparent; border: none;
}
.stTabs [aria-selected="true"] {
    color: #15803d !important; font-weight: 600 !important;
    border-bottom: 2px solid #16a34a !important;
    background: transparent !important;
}

/* ── Expanders ─────────────────────────────────────────────────────────────── */
.stExpander > details {
    border: 1px solid #e5e7eb !important; border-radius: 8px !important;
    background: #ffffff !important;
}
.stExpander summary {
    font-size: 0.875rem !important; font-weight: 600 !important; color: #374151 !important;
}

/* ── Progress bars ─────────────────────────────────────────────────────────── */
.stProgress > div > div { background-color: #16a34a !important; border-radius: 4px !important; }

/* ── Alerts ────────────────────────────────────────────────────────────────── */
[data-testid="stNotification"] { border-radius: 8px !important; }

/* ── Evidence viewer ───────────────────────────────────────────────────────── */
.tr-evidence-box {
    background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px;
    padding: 1rem 1.25rem; margin: 0.5rem 0;
}
.tr-evidence-label {
    font-size: 0.75rem; font-weight: 600; color: #15803d;
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;
}
.tr-evidence-text {
    font-size: 0.875rem; color: #111827; line-height: 1.6;
}
.tr-source-ref {
    display: inline-flex; align-items: center; gap: 0.4rem;
    background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px;
    padding: 0.3rem 0.7rem; font-size: 0.78rem; color: #374151;
    font-weight: 500; margin-top: 0.6rem;
}

/* ── Empty state ───────────────────────────────────────────────────────────── */
.tr-empty {
    text-align: center; padding: 3rem 1rem; background: #ffffff;
    border: 1px dashed #d1d5db; border-radius: 8px; color: #9ca3af;
}
.tr-empty-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
.tr-empty-title { font-size: 1rem; font-weight: 600; color: #374151; margin-bottom: 0.4rem; }
.tr-empty-desc { font-size: 0.875rem; }

/* ── Upload area ───────────────────────────────────────────────────────────── */
[data-testid="stFileUploader"] {
    border: 2px dashed #d1d5db !important; border-radius: 8px !important;
    background: #fafafa !important; transition: border-color 0.15s !important;
}
[data-testid="stFileUploader"]:hover { border-color: #16a34a !important; }

/* ── Metric ────────────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 0.85rem 1rem !important;
}
[data-testid="stMetricLabel"] { font-size: 0.75rem !important; color: #9ca3af !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] { font-size: 1.5rem !important; color: #111827 !important; font-weight: 700 !important; }

/* ── Login page ────────────────────────────────────────────────────────────── */
.tr-login-wrapper {
    max-width: 420px; margin: 2rem auto; background: #ffffff;
    border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 2rem 2rem; box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.tr-login-logo {
    text-align: center; margin-bottom: 1.5rem;
}
.tr-login-logo h1 {
    font-size: 1.75rem; font-weight: 800; color: #0f2318; margin: 0.5rem 0 0.25rem;
}
.tr-login-logo p { font-size: 0.875rem; color: #6b7280; margin: 0; }

/* ── Offline secure banner ─────────────────────────────────────────────────── */
.tr-offline-banner {
    background: #0f2318; border: 1px solid #1e3a28; border-radius: 8px;
    padding: 0.65rem 1rem; margin-bottom: 0.75rem;
    display: flex; align-items: center; gap: 0.6rem;
}
.tr-offline-banner-text {
    font-size: 0.8rem; font-weight: 700; color: #4ade80; letter-spacing: 0.03em;
}
.tr-offline-banner-sub {
    font-size: 0.72rem; color: #64748b;
}

/* ── Scrollbar ─────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #9ca3af; }

/* ── Responsive ────────────────────────────────────────────────────────────── */
@media (max-width: 768px) {
    .block-container { padding: 1rem 0.5rem !important; }
    .tr-topbar { flex-direction: column; gap: 0.5rem; align-items: flex-start; }
}
</style>
"""


# ── Public functions ──────────────────────────────────────────────────────────

def apply_enterprise_theme() -> None:
    """Inject the master enterprise CSS — call once per page render."""
    st.markdown(MASTER_CSS, unsafe_allow_html=True)


def render_top_navbar(user: dict, page_title: str = "Home") -> None:
    """
    Unified top navigation bar shown on every page for every role.
    Shows: page title | role badge | username
    """
    role_lbl = user.get("role", "user").replace("factchecker", "Fact-Checker").title()
    name     = user.get("name", user.get("username", "User"))

    st.markdown(f"""
    <div class="tr-topbar">
        <div class="tr-topbar-left">
            <span class="tr-topbar-title">{page_title}</span>
            <span class="tr-badge tr-badge-gray">👤 {role_lbl}</span>
        </div>
        <div class="tr-topbar-right">
            Signed in as <strong>{name}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_page_header(title: str, description: str = "", icon: str = "") -> None:
    """Standard page header with title and optional description."""
    prefix = f"{icon} " if icon else ""
    st.markdown(f"""
    <div class="tr-page-header">
        <div class="tr-page-title">{prefix}{title}</div>
        {"<div class='tr-page-desc'>" + description + "</div>" if description else ""}
    </div>
    """, unsafe_allow_html=True)


def stat_row(stats: list[dict]) -> None:
    """
    Render a row of stat boxes.
    Each dict: {label, value, sub="", color="#111827"}
    """
    cols = st.columns(len(stats))
    for col, s in zip(cols, stats):
        color = s.get("color", "#111827")
        sub   = s.get("sub", "")
        with col:
            st.markdown(f"""
            <div class="tr-stat">
                <div class="tr-stat-label">{s['label']}</div>
                <div class="tr-stat-value" style="color:{color};">{s['value']}</div>
                {"<div class='tr-stat-sub'>" + sub + "</div>" if sub else ""}
            </div>
            """, unsafe_allow_html=True)


def status_badge_html(status: str) -> str:
    """Return HTML badge for answer/conflict/refuse status."""
    cfg = {
        "answer":   ("tr-badge-green",  "✓ Verified"),
        "conflict": ("tr-badge-amber",  "⚠ Conflict"),
        "refuse":   ("tr-badge-red",    "✗ Not Found"),
    }
    cls, lbl = cfg.get(status, ("tr-badge-gray", status.title()))
    return f'<span class="tr-badge {cls}">{lbl}</span>'


def evidence_box(text: str, doc: str, page: int, status: str = "answer") -> None:
    """Render a grounded evidence block with source reference."""
    badge = status_badge_html(status)
    st.markdown(f"""
    <div class="tr-evidence-box">
        <div class="tr-evidence-label">Evidence {badge}</div>
        <div class="tr-evidence-text">{text}</div>
        <div class="tr-source-ref">📄 {doc} &nbsp;·&nbsp; Page {page}</div>
    </div>
    """, unsafe_allow_html=True)


def empty_state(title: str, description: str = "", icon: str = "📭") -> None:
    """Render a clean empty state placeholder."""
    st.markdown(f"""
    <div class="tr-empty">
        <div class="tr-empty-icon">{icon}</div>
        <div class="tr-empty-title">{title}</div>
        {"<div class='tr-empty-desc'>" + description + "</div>" if description else ""}
    </div>
    """, unsafe_allow_html=True)


def offline_banner() -> None:
    """Render the offline secure banner in the sidebar."""
    st.sidebar.markdown("""
    <div class="tr-offline-banner">
        <span style="font-size:1.1rem;">🔒</span>
        <div>
            <div class="tr-offline-banner-text">OFFLINE SECURE</div>
            <div class="tr-offline-banner-sub">Air-gapped · Zero external APIs</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_dashboard_metrics(doc_count: int, fact_count: int,
                              audit_ok: bool, refusal_count: int = 0) -> None:
    """Standard KPI metrics row for dashboards."""
    stat_row([
        {"label": "Documents",    "value": str(doc_count)},
        {"label": "Indexed Facts","value": f"{fact_count:,}"},
        {"label": "Audit Chain",  "value": "✅ Intact" if audit_ok else "❌ Broken",
         "color": "#15803d" if audit_ok else "#b91c1c"},
        {"label": "Refusals",     "value": str(refusal_count)},
    ])
