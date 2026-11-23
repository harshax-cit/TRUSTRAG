"""
tracerag/ui.py – Enterprise UI Design System for TraceRAG.

Design Language:
  - Dark forest-green sidebar (#0f281e, #143526)
  - Light-grey / white workspace (#f8faf9, #ffffff)
  - Deep green primary buttons (#15803d, #166534)
  - Subtle mint-green highlights (#10b981, #ecfdf5, #d1fae5)
  - Charcoal typography (#111827, #1f2937, #374151)
  - Thin borders (#e5e7eb)
  - Subtle shadows (0 1px 3px rgba(0,0,0,0.06))
  - Professional enterprise SaaS aesthetic
"""

from __future__ import annotations

import streamlit as st


ENTERPRISE_CSS = """
<style>
/* Global Layout & Typography */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #1f2937;
    background-color: #f8faf9;
}

/* App background */
.stApp {
    background-color: #f8faf9;
}

/* Sidebar Styling: Dark Forest Green */
[data-testid="stSidebar"] {
    background-color: #0f281e !important;
    border-right: 1px solid #1c4532 !important;
}

[data-testid="stSidebar"] * {
    color: #e2e8f0 !important;
}

[data-testid="stSidebar"] h1, 
[data-testid="stSidebar"] h2, 
[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
    font-weight: 700 !important;
}

[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextArea label,
[data-testid="stSidebar"] .stRadio label {
    color: #cbd5e1 !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
}

/* Primary and Regular Buttons */
.stButton > button[kind="primary"],
div.stButton > button:first-child[kind="primary"] {
    background-color: #15803d !important;
    color: #ffffff !important;
    border: 1px solid #166534 !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1rem !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
    transition: all 0.15s ease-in-out !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: #166534 !important;
    border-color: #14532d !important;
}

.stButton > button:not([kind="primary"]) {
    background-color: #ffffff !important;
    color: #374151 !important;
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
}

.stButton > button:not([kind="primary"]):hover {
    background-color: #f3f4f6 !important;
    border-color: #9ca3af !important;
}

/* Top Navigation Bar */
.top-navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0.75rem 1.25rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

.top-nav-left {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.top-nav-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f281e;
    margin: 0;
}

.top-nav-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.65rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-offline {
    background-color: #fef2f2;
    color: #991b1b;
    border: 1px solid #fecaca;
}

.badge-online {
    background-color: #ecfdf5;
    color: #065f46;
    border: 1px solid #a7f3d0;
}

.badge-role {
    background-color: #f0fdf4;
    color: #166534;
    border: 1px solid #bbf7d0;
}

.top-nav-right {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    font-size: 0.875rem;
}

/* Cards & Dashboard Widgets */
.dashboard-card {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.dashboard-card:hover {
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.07);
}

.card-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: #111827;
    margin-bottom: 0.35rem;
}

.card-desc {
    font-size: 0.825rem;
    color: #6b7280;
    line-height: 1.4;
    margin-bottom: 0.75rem;
}

/* Metrics & Stats */
.stat-box {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1rem;
    text-align: left;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.stat-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    font-weight: 600;
    color: #6b7280;
    letter-spacing: 0.05em;
    margin-bottom: 0.25rem;
}

.stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: #0f281e;
}

/* Verification Pill Badges */
.badge-verified {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    background-color: #ecfdf5;
    color: #047857;
    border: 1px solid #6ee7b7;
    padding: 0.2rem 0.55rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
}

.badge-conflict {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    background-color: #fffbeb;
    color: #b45309;
    border: 1px solid #fcd34d;
    padding: 0.2rem 0.55rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
}

.badge-refuse {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    background-color: #fef2f2;
    color: #b91c1c;
    border: 1px solid #fca5a5;
    padding: 0.2rem 0.55rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
}

/* Tables */
.enterprise-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    overflow: hidden;
}

.enterprise-table th {
    background-color: #f9fafb;
    color: #4b5563;
    font-weight: 600;
    text-align: left;
    padding: 0.65rem 0.85rem;
    border-bottom: 1px solid #e5e7eb;
}

.enterprise-table td {
    padding: 0.65rem 0.85rem;
    border-bottom: 1px solid #f3f4f6;
    color: #1f2937;
}

.enterprise-table tr:hover td {
    background-color: #f9fafb;
}

/* Clean Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 6px;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 2px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 6px 6px 0 0;
    padding: 8px 16px;
    font-weight: 500;
    color: #4b5563;
}

.stTabs [aria-selected="true"] {
    background-color: #ffffff !important;
    color: #15803d !important;
    border-bottom: 2px solid #15803d !important;
    font-weight: 600;
}
</style>
"""


def apply_enterprise_theme():
    """Inject the dark forest-green enterprise CSS styling."""
    st.markdown(ENTERPRISE_CSS, unsafe_allow_html=True)


def render_top_navbar(user: dict, title: str = "TraceRAG Enterprise"):
    """
    Renders top navigation header with:
      - Title & Breadcrumb
      - Role badge
      - Environment indicator (Offline vs Online)
      - User profile display
    """
    is_gov = user.get("offline", False) or user.get("role") == "government"
    env_class = "badge-offline" if is_gov else "badge-online"
    env_icon = "🔒" if is_gov else "🌐"
    env_text = "OFFLINE SECURE" if is_gov else "ONLINE ACTIVE"
    
    role_name = user.get("role", "analyst").capitalize()
    user_name = user.get("name", "User")
    
    html = f"""
    <div class="top-navbar">
        <div class="top-nav-left">
            <span class="top-nav-title">{title}</span>
            <span class="top-nav-badge {env_class}">{env_icon} {env_text}</span>
            <span class="top-nav-badge badge-role">👤 Role: {role_name}</span>
        </div>
        <div class="top-nav-right">
            <span>Signed in as <strong>{user_name}</strong></span>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_dashboard_metrics(doc_count: int, fact_count: int, audit_ok: bool, refusal_count: int = 0):
    """Render the standard top KPI metrics row for the dashboard."""
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Accessible Documents</div>
            <div class="stat-value">{doc_count}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Indexed Facts</div>
            <div class="stat-value">{fact_count:,}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        status_label = "✅ INTACT" if audit_ok else "❌ BROKEN"
        status_color = "#047857" if audit_ok else "#b91c1c"
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Audit Log Chain</div>
            <div class="stat-value" style="color: {status_color}; font-size: 1.25rem;">{status_label}</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Verification Refusals</div>
            <div class="stat-value">{refusal_count}</div>
        </div>
        """, unsafe_allow_html=True)
