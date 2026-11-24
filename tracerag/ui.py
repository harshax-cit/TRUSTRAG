"""
tracerag/ui.py - Shared design system for TraceRAG.

Provides apply_enterprise_theme() and all reusable components.
Every role uses these same primitives - only content changes.
"""

from __future__ import annotations
import streamlit as st

# ── CSS ───────────────────────────────────────────────────────────────────────
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

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #0f2318 !important;
    border-right: 1px solid #1e3a28 !important;
}
[data-testid="stSidebar"] * { color: #cbd5e1 !important; }
[data-testid="stSidebar"] strong { color: #ffffff !important; }
[data-testid="stSidebar"] hr { border-color: #1e3a28 !important; margin: 0.6rem 0 !important; }
[data-testid="stSidebar"] [data-testid="stRadioOptions"] label {
    text-transform: none !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    color: #94a3b8 !important;
    padding: 0.4rem 0.6rem !important;
    border-radius: 6px !important;
    cursor: pointer;
}
[data-testid="stSidebar"] [data-testid="stRadioOptions"] [aria-checked="true"] + label {
    color: #ffffff !important;
    background-color: #1a3d2b !important;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] .stButton > button {
    background-color: transparent !important;
    color: #94a3b8 !important;
    border: 1px solid #1e3a28 !important;
    font-size: 0.8rem !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #1a3d2b !important;
    color: #ffffff !important;
}

/* ── Buttons ── */
div.stButton > button[kind="primary"] {
    background-color: #16a34a !important;
    color: #ffffff !important;
    border: 1px solid #15803d !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    padding: 0.5rem 1.25rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
    transition: background-color 0.15s !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #15803d !important;
}
div.stButton > button:not([kind="primary"]) {
    background-color: #ffffff !important;
    color: #374151 !important;
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
}
div.stButton > button:not([kind="primary"]):hover {
    background-color: #f9fafb !important;
    border-color: #9ca3af !important;
}

/* ── Inputs ── */
.stTextInput input, .stTextArea textarea,
.stSelectbox select, .stNumberInput input {
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    font-size: 0.875rem !important;
    color: #111827 !important;
    background-color: #ffffff !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #16a34a !important;
    box-shadow: 0 0 0 3px rgba(22,163,74,0.1) !important;
}
.stTextInput label, .stTextArea label,
.stSelectbox label, .stNumberInput label {
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    color: #374151 !important;
}

/* ── Cards ── */
.tr-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    transition: box-shadow 0.15s;
    margin-bottom: 0.75rem;
}
.tr-card:hover { box-shadow: 0 4px 8px rgba(0,0,0,0.07); }
.tr-card-sm {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    margin-bottom: 0.5rem;
}

/* ── Topbar ── */
.tr-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0.65rem 1.1rem;
    margin-bottom: 1.25rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.tr-topbar-left  { display: flex; align-items: center; gap: 0.75rem; }
.tr-topbar-title { font-weight: 700; font-size: 1rem; color: #111827; margin: 0; }
.tr-topbar-right { font-size: 0.8rem; color: #6b7280; }
.tr-topbar-right strong { color: #111827; }

/* ── Page header ── */
.tr-ph { padding-bottom: 1rem; border-bottom: 1px solid #e5e7eb; margin-bottom: 1.5rem; }
.tr-ph-title { font-size: 1.35rem; font-weight: 700; color: #111827; margin: 0 0 0.25rem; }
.tr-ph-desc  { font-size: 0.875rem; color: #6b7280; margin: 0; }

/* ── Stat box ── */
.tr-stat {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 1rem 1.25rem; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.tr-stat-label {
    font-size: 0.72rem; font-weight: 600; color: #9ca3af;
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.4rem;
}
.tr-stat-value { font-size: 1.75rem; font-weight: 700; color: #111827; line-height: 1; }
.tr-stat-sub   { font-size: 0.75rem; color: #6b7280; margin-top: 0.2rem; }

/* ── Badges ── */
.tr-badge {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.2rem 0.6rem; border-radius: 9999px;
    font-size: 0.72rem; font-weight: 600; white-space: nowrap;
}
.tr-badge-green  { background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; }
.tr-badge-amber  { background:#fffbeb; color:#b45309; border:1px solid #fde68a; }
.tr-badge-red    { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
.tr-badge-blue   { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; }
.tr-badge-gray   { background:#f9fafb; color:#4b5563; border:1px solid #e5e7eb; }

/* ── Evidence box ── */
.tr-ev {
    background: #f0fdf4; border: 1px solid #bbf7d0;
    border-radius: 8px; padding: 1rem 1.25rem; margin: 0.5rem 0;
}
.tr-ev-label {
    font-size: 0.72rem; font-weight: 600; color: #15803d;
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem;
}
.tr-ev-text { font-size: 0.875rem; color: #111827; line-height: 1.6; }
.tr-src {
    display: inline-flex; align-items: center; gap: 0.4rem;
    background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px;
    padding: 0.25rem 0.65rem; font-size: 0.78rem; color: #374151;
    font-weight: 500; margin-top: 0.6rem;
}

/* ── Empty state ── */
.tr-empty {
    text-align: center; padding: 3rem 1rem;
    background: #ffffff; border: 1px dashed #d1d5db;
    border-radius: 8px; color: #9ca3af;
}
.tr-empty-icon  { font-size: 2.25rem; margin-bottom: 0.75rem; }
.tr-empty-title { font-size: 1rem; font-weight: 600; color: #374151; margin-bottom: 0.35rem; }
.tr-empty-desc  { font-size: 0.875rem; }

/* ── Tables ── */
.stDataFrame { border: 1px solid #e5e7eb !important; border-radius: 8px !important; overflow: hidden !important; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid #e5e7eb; }
.stTabs [data-baseweb="tab"] {
    padding: 0.5rem 1rem; border-radius: 6px 6px 0 0;
    font-size: 0.875rem; font-weight: 500; color: #6b7280; background: transparent;
}
.stTabs [aria-selected="true"] {
    color: #15803d !important; font-weight: 600 !important;
    border-bottom: 2px solid #16a34a !important; background: transparent !important;
}

/* ── Expander ── */
.stExpander > details {
    border: 1px solid #e5e7eb !important; border-radius: 8px !important; background: #fff !important;
}

/* ── Metric ── */
[data-testid="stMetric"] {
    background: #fff; border: 1px solid #e5e7eb;
    border-radius: 8px; padding: 0.85rem 1rem !important;
}
[data-testid="stMetricLabel"] { font-size: 0.72rem !important; color: #9ca3af !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] { font-size: 1.5rem  !important; color: #111827 !important; font-weight: 700 !important; }

/* ── Upload ── */
[data-testid="stFileUploader"] {
    border: 2px dashed #d1d5db !important; border-radius: 8px !important;
    background: #fafafa !important;
}
[data-testid="stFileUploader"]:hover { border-color: #16a34a !important; }

/* ── Progress ── */
.stProgress > div > div { background-color: #16a34a !important; border-radius: 4px !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }

/* ── Login page ── */
.tr-login-panel {
    background: #ffffff; border: 1px solid #e5e7eb;
    border-radius: 12px; padding: 2.5rem 2rem;
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.tr-login-brand { margin-bottom: 2rem; }
.tr-login-brand h1 {
    font-size: 1.75rem; font-weight: 800; color: #0f2318; margin: 0.6rem 0 0.3rem;
}
.tr-login-brand p { font-size: 0.875rem; color: #6b7280; margin: 0; }

/* ── Hero panel (login left side) ── */
.tr-hero {
    background: linear-gradient(160deg, #0f2318 0%, #1a3d2b 100%);
    border-radius: 12px; padding: 2.5rem 2rem; height: 100%;
    display: flex; flex-direction: column; justify-content: center;
}
.tr-hero h2 { color: #ffffff; font-size: 1.75rem; font-weight: 800; margin: 0 0 0.75rem; }
.tr-hero p  { color: #94a3b8; font-size: 0.9rem; line-height: 1.6; margin: 0 0 1.5rem; }
.tr-hero-feat {
    display: flex; align-items: flex-start; gap: 0.65rem; margin-bottom: 0.85rem;
}
.tr-hero-feat-icon { font-size: 1.1rem; margin-top: 0.1rem; }
.tr-hero-feat-text { font-size: 0.85rem; color: #cbd5e1; line-height: 1.4; }
.tr-hero-feat-text strong { color: #ffffff; }

@media (max-width: 768px) {
    .block-container { padding: 1rem 0.5rem !important; }
    .tr-topbar { flex-direction: column; gap: 0.5rem; align-items: flex-start; }
}
</style>
"""

# Export for tests
ENTERPRISE_CSS = _CSS

# ── Role definitions ──────────────────────────────────────────────────────────
ROLES = {
    "Government": {
        "icon": "🏛️",
        "pages": [
            "Dashboard", "Document Repository", "Upload Documents",
            "Evidence Search", "Verification", "Conflicts & Revisions",
            "Audit Centre", "System Status",
        ],
        "description": "Secure document intelligence and evidence verification.",
    },
    "Policy Analyst": {
        "icon": "📊",
        "pages": [
            "Dashboard", "Research Workspace", "Compare Documents",
            "Trend Analysis", "Policy Briefs", "Citation Viewer",
            "Export & Reports",
        ],
        "description": "Research, compare and derive policy insights from reports.",
    },
    "Journalist": {
        "icon": "📰",
        "pages": [
            "Dashboard", "Fact-Check Workspace", "Article Research",
            "Source Viewer", "Stale-Number Alerts", "Conflicts",
            "Verification Receipts",
        ],
        "description": "Verify claims and collect citation-ready evidence.",
    },
    "Student": {
        "icon": "🎓",
        "pages": [
            "Dashboard", "Ask a Question", "AI Document Tutor",
            "Glossary & Terms", "Study Notes", "Saved Answers",
            "Learning History",
        ],
        "description": "Learn from reports with clear, evidence-backed explanations.",
    },
    "Fact-Checker": {
        "icon": "🔍",
        "pages": [
            "Dashboard", "Verify Claim", "Cross-Document Check",
            "Evidence Comparison", "Conflict Detection",
            "Reports & Exports", "Verification History",
        ],
        "description": "Independently verify claims against multiple documents.",
    },
    "Auditor / Admin": {
        "icon": "🛡️",
        "pages": [
            "Dashboard", "Audit Logs", "HMAC Integrity",
            "Verification Reviews", "Refusal Ledger", "User Activity",
            "Document Access", "System Reports", "User & Role Management",
        ],
        "description": "Monitor system integrity, audit activity and access.",
    },
}

# Map TraceRAG internal role names → ROLES keys
ROLE_NAME_MAP = {
    "government":  "Government",
    "analyst":     "Policy Analyst",
    "journalist":  "Journalist",
    "student":     "Student",
    "factchecker": "Fact-Checker",
    "auditor":     "Auditor / Admin",
}


def apply_enterprise_theme() -> None:
    """Inject master CSS - call once at the top of every render."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ── Design tokens (used by role_views.py) ────────────────────────────────────
COLORS = {
    "success_text":  "#15803d",
    "danger_text":   "#b91c1c",
    "warn_text":     "#b45309",
    "info_text":     "#1d4ed8",
    "text":          "#111827",
    "text_secondary":"#6b7280",
    "primary":       "#16a34a",
    "sidebar_bg":    "#0f2318",
    "border":        "#e5e7eb",
}


def render_sidebar(user: dict, nav_key: str) -> str:
    """
    Render the shared sidebar shell and return the selected page name.
    Brand · Navigation · User profile · Sign-out
    All six roles call this same function.
    """
    role_key  = user.get("role", "analyst").lower()
    role_name = ROLE_NAME_MAP.get(role_key, "Policy Analyst")
    role_cfg  = ROLES.get(role_name, ROLES["Policy Analyst"])
    name      = user.get("name", user.get("username", "User"))

    # ── Brand ──────────────────────────────────────────────────────────────────
    st.sidebar.markdown("""
    <div style="padding:0.75rem 0 1.25rem;">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
            <span style="font-size:1.5rem;line-height:1;">🌿</span>
            <span style="font-size:1.2rem;font-weight:800;color:#fff;letter-spacing:-0.02em;">
                TraceRAG
            </span>
        </div>
        <div style="font-size:0.72rem;color:#64748b;padding-left:0.1rem;">
            Multimodal RAG with Explainability
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.sidebar.markdown("<hr/>", unsafe_allow_html=True)

    # ── Navigation ─────────────────────────────────────────────────────────────
    st.sidebar.markdown(
        "<div style='font-size:0.7rem;font-weight:700;color:#475569;"
        "text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.4rem;'>"
        "Navigation</div>",
        unsafe_allow_html=True,
    )
    sel = st.sidebar.radio(
        "nav", role_cfg["pages"], key=nav_key,
        label_visibility="collapsed",
    )
    page = sel if sel else role_cfg["pages"][0]

    st.sidebar.markdown("<hr/>", unsafe_allow_html=True)

    # ── User profile ───────────────────────────────────────────────────────────
    st.sidebar.markdown(f"""
    <div style="padding:0.3rem 0 0.6rem;">
        <div style="font-size:0.72rem;color:#64748b;margin-bottom:0.2rem;">Signed in as</div>
        <div style="font-size:0.9rem;font-weight:700;color:#fff;">{name}</div>
        <div style="font-size:0.75rem;color:#64748b;margin-top:0.1rem;">
            {role_cfg['icon']} {role_name}
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("Sign out", key=f"signout_{nav_key}",
                          use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    return page


def render_topbar(user: dict, page: str) -> None:
    """Topbar: page title · role badge · username."""
    role_key  = user.get("role", "analyst").lower()
    role_name = ROLE_NAME_MAP.get(role_key, "Policy Analyst")
    role_icon = ROLES.get(role_name, {}).get("icon", "👤")
    name      = user.get("name", user.get("username", "User"))

    st.markdown(f"""
    <div class="tr-topbar">
        <div class="tr-topbar-left">
            <span class="tr-topbar-title">{page}</span>
            <span class="tr-badge tr-badge-gray">{role_icon} {role_name}</span>
        </div>
        <div class="tr-topbar-right">Signed in as <strong>{name}</strong></div>
    </div>
    """, unsafe_allow_html=True)


def page_header(title: str, description: str = "", icon: str = "") -> None:
    """Standard page header."""
    prefix = f"{icon} " if icon else ""
    desc_html = f"<div class='tr-ph-desc'>{description}</div>" if description else ""
    st.markdown(f"""
    <div class="tr-ph">
        <div class="tr-ph-title">{prefix}{title}</div>
        {desc_html}
    </div>
    """, unsafe_allow_html=True)


def stat_row(stats: list[dict]) -> None:
    """
    Row of stat boxes.
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


def badge(text: str, kind: str = "gray") -> str:
    """Return an inline HTML badge. kind: green|amber|red|blue|gray"""
    return f'<span class="tr-badge tr-badge-{kind}">{text}</span>'


def status_badge(status: str) -> str:
    """Return HTML badge for answer/conflict/refuse."""
    cfg = {
        "answer":   ("green", "✓ Verified"),
        "conflict": ("amber", "⚠ Conflict"),
        "refuse":   ("red",   "✗ Not Found"),
    }
    kind, lbl = cfg.get(status, ("gray", status.title()))
    return badge(lbl, kind)


def evidence_box(text: str, doc: str, page: int, status: str = "answer") -> None:
    """Grounded evidence block with source reference."""
    b = status_badge(status)
    st.markdown(f"""
    <div class="tr-ev">
        <div class="tr-ev-label">Evidence {b}</div>
        <div class="tr-ev-text">{text}</div>
        <div class="tr-src">📄 {doc} &nbsp;·&nbsp; Page {page}</div>
    </div>
    """, unsafe_allow_html=True)


def empty_state(title: str, desc: str = "", icon: str = "📭") -> None:
    """Clean empty-state placeholder."""
    st.markdown(f"""
    <div class="tr-empty">
        <div class="tr-empty-icon">{icon}</div>
        <div class="tr-empty-title">{title}</div>
        {"<div class='tr-empty-desc'>" + desc + "</div>" if desc else ""}
    </div>
    """, unsafe_allow_html=True)


def render_login(on_login) -> None:
    """
    Professional split-panel login screen.
    on_login(username, password) → called when form submitted.
    """
    left, right = st.columns([1.05, 1], gap="large")

    # ── Left: hero panel ───────────────────────────────────────────────────────
    with left:
        st.markdown("""
        <div class="tr-hero">
            <div style="font-size:2.2rem;margin-bottom:0.75rem;">🌿</div>
            <h2>Evidence Intelligence<br>for Every Role</h2>
            <p>
                TraceRAG traces every answer to its source document,
                page, and bounding box. No hallucinations.
                No unverified numbers.
            </p>
            <div class="tr-hero-feat">
                <div class="tr-hero-feat-icon">📄</div>
                <div class="tr-hero-feat-text">
                    <strong>Source-grounded answers</strong><br>
                    Every answer cites document, page and region.
                </div>
            </div>
            <div class="tr-hero-feat">
                <div class="tr-hero-feat-icon">🔍</div>
                <div class="tr-hero-feat-text">
                    <strong>Claim-to-pixel verification</strong><br>
                    Numbers verified in the original PDF image.
                </div>
            </div>
            <div class="tr-hero-feat">
                <div class="tr-hero-feat-icon">🛡️</div>
                <div class="tr-hero-feat-text">
                    <strong>HMAC audit chain</strong><br>
                    Tamper-evident log of every query and decision.
                </div>
            </div>
            <div class="tr-hero-feat">
                <div class="tr-hero-feat-icon">🔒</div>
                <div class="tr-hero-feat-text">
                    <strong>Government offline mode</strong><br>
                    Air-gapped, zero external API calls.
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Right: login panel ─────────────────────────────────────────────────────
    with right:
        st.markdown('<div class="tr-login-panel">', unsafe_allow_html=True)

        st.markdown("""
        <div class="tr-login-brand">
            <div style="font-size:1.75rem;">🌿</div>
            <h1>TraceRAG</h1>
            <p>Enterprise Multimodal Evidence-Intelligence Platform</p>
        </div>
        """, unsafe_allow_html=True)

        tab_in, tab_reg = st.tabs(["Sign In", "Create Account"])

        with tab_in:
            with st.form("login_form"):
                username = st.text_input("Username", placeholder="your-username")
                password = st.text_input("Password", type="password",
                                          placeholder="your-password")
                btn = st.form_submit_button("Sign in →", type="primary",
                                             use_container_width=True)
            if btn:
                on_login(username, password, mode="login")

        with tab_reg:
            st.caption("Government and Auditor accounts require administrator provisioning.")
            with st.form("register_form"):
                rn  = st.text_input("Full Name",        placeholder="Your Name")
                ru  = st.text_input("Username",         placeholder="choose-a-username")
                rp  = st.text_input("Password",         type="password",
                                     placeholder="at least 6 characters")
                rp2 = st.text_input("Confirm Password", type="password")
                rr  = st.selectbox("Role", ["Student", "Policy Analyst",
                                             "Journalist", "Fact-Checker"],
                                    format_func=lambda r: {
                                        "Student":       "🎓 Student",
                                        "Policy Analyst":"📊 Policy Analyst",
                                        "Journalist":    "📰 Journalist",
                                        "Fact-Checker":  "🔍 Fact-Checker",
                                    }.get(r, r))
                rbtn = st.form_submit_button("Create Account →", type="primary",
                                              use_container_width=True)
            if rbtn:
                if rp != rp2:
                    st.error("Passwords do not match.")
                else:
                    on_login(ru, rp, mode="register",
                             name=rn, role=rr)

        st.markdown('</div>', unsafe_allow_html=True)


# ── Backward-compat aliases used by existing code ────────────────────────────
def render_top_navbar(user: dict, page_title: str = "Home", **_) -> None:
    render_topbar(user, page_title)


def render_dashboard_metrics(doc_count: int, fact_count: int,
                              audit_ok: bool, refusal_count: int = 0) -> None:
    stat_row([
        {"label": "Documents",    "value": str(doc_count)},
        {"label": "Indexed Facts","value": f"{fact_count:,}"},
        {"label": "Audit Chain",
         "value": "Intact" if audit_ok else "⚠ Broken",
         "color": "#15803d" if audit_ok else "#b91c1c"},
        {"label": "Refusals",     "value": str(refusal_count)},
    ])


def render_page_header(title: str, description: str = "", icon: str = "") -> None:
    page_header(title, description, icon)


def offline_banner() -> None:
    pass  # removed per design requirements
