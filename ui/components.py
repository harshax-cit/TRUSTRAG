"""
ui/components.py - Reusable TraceRAG UI components.

All components return HTML strings or call st.markdown.
No emoji in UI text. Use text labels + CSS for status.
"""

from __future__ import annotations
import streamlit as st
from .theme import STATUS_COLORS, inject_theme


# ── card ──────────────────────────────────────────────────────────────────────

def card(content_fn, variant: str = "default", key: str = "") -> None:
    """
    Wrapper that renders content_fn() inside a card div.
    variant: default | sm | navy
    """
    cls = {"default": "tr-card", "sm": "tr-card-sm", "navy": "tr-card-navy"}[variant]
    st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
    content_fn()
    st.markdown("</div>", unsafe_allow_html=True)


# ── badge ─────────────────────────────────────────────────────────────────────

def badge(status: str) -> str:
    """
    Return HTML badge for answer / conflict / refuse.
    Always uses text + color — never color alone.
    """
    cfg = STATUS_COLORS.get(status, {"bg": "#F4F7FA", "text": "#5B6878", "label": status.title()})
    cls = f"tr-badge tr-badge-{status}"
    bg   = cfg["bg"]
    fg   = cfg["text"]
    lbl  = cfg["label"]
    return (
        f'<span class="{cls}" '
        f'style="background:{bg};color:{fg};" '
        f'aria-label="Status: {lbl}">'
        f'{lbl}</span>'
    )


def badge_html(status: str) -> None:
    st.markdown(badge(status), unsafe_allow_html=True)


# ── pill ──────────────────────────────────────────────────────────────────────

def pill(text: str, tone: str = "gray") -> str:
    """
    tone: online | offline | teal | amber | gray
    Returns HTML string.
    """
    cls_map = {
        "online":  "tr-badge tr-badge-online",
        "offline": "tr-badge tr-badge-offline",
        "teal":    "tr-badge tr-badge-teal",
        "amber":   "tr-badge tr-badge-amber",
        "gray":    "tr-badge tr-badge-gray",
    }
    cls = cls_map.get(tone, "tr-badge tr-badge-gray")
    return f'<span class="{cls}">{text}</span>'


def pill_html(text: str, tone: str = "gray") -> None:
    st.markdown(pill(text, tone), unsafe_allow_html=True)


# ── metric_tile ───────────────────────────────────────────────────────────────

def metric_tile(label: str, value: str, caption: str = "",
                col=None) -> None:
    """Render a metric tile. Pass col to render inside an st.column."""
    cap_html = f"<div class='tr-metric-cap'>{caption}</div>" if caption else ""
    html = f"""
    <div class="tr-metric">
        <div class="tr-metric-label">{label}</div>
        <div class="tr-metric-value">{value}</div>
        {cap_html}
    </div>
    """
    if col:
        with col:
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)


# ── source_chip ───────────────────────────────────────────────────────────────

def source_chip(doc: str, page: int, verified: bool = True) -> str:
    """Return an inline HTML source reference chip."""
    dot_cls = "tr-source-verified" if verified else ""
    v_label = "Verified" if verified else "Unverified"
    short_doc = doc[-28:] if len(doc) > 28 else doc
    return (
        f'<span class="tr-source {dot_cls}" '
        f'title="{doc}, page {page} — {v_label}" '
        f'role="img" aria-label="Source: {doc} page {page}">'
        f'{short_doc} · p.{page}'
        f'</span>'
    )


def source_chip_html(doc: str, page: int, verified: bool = True) -> None:
    st.markdown(source_chip(doc, page, verified), unsafe_allow_html=True)


# ── empty_state ───────────────────────────────────────────────────────────────

def empty_state(title: str, hint: str = "", action: str = "") -> None:
    """Clean empty-state placeholder."""
    st.markdown(f"""
    <div class="tr-empty" role="status" aria-label="{title}">
        <div class="tr-empty-title">{title}</div>
        {"<div class='tr-empty-hint'>" + hint + "</div>" if hint else ""}
    </div>
    """, unsafe_allow_html=True)
    if action:
        st.caption(action)


# ── stepper ───────────────────────────────────────────────────────────────────

def stepper(stages: list[str], current: int) -> None:
    """
    Render a horizontal step indicator.
    current is 0-indexed. Done = < current, Active = current, Pending = > current.
    """
    parts = []
    for i, stage in enumerate(stages):
        if i < current:
            cls = "tr-step tr-step-done"
            label = f"Done: {stage}"
        elif i == current:
            cls = "tr-step tr-step-active"
            label = f"Current step: {stage}"
        else:
            cls = "tr-step"
            label = stage
        parts.append(f'<div class="{cls}" aria-label="{label}">{stage}</div>')
    st.markdown(
        f'<div class="tr-stepper" role="list">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


# ── progress_bar ──────────────────────────────────────────────────────────────

def progress_bar(value: float, label: str = "") -> None:
    """
    value: 0.0 – 1.0
    Uses st.progress with an accessible label.
    """
    pct = round(value * 100)
    if label:
        st.caption(f"{label} — {pct}%")
    st.progress(value)


# ── page_header ───────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = "", tag: str = "") -> None:
    """
    Serif page title with optional subtitle and optional tag
    (e.g. 'Sample data').
    """
    tag_html = ""
    if tag:
        tag_html = f'<span class="tr-badge tr-badge-gray" style="font-size:11px;vertical-align:middle;margin-left:0.6rem;">{tag}</span>'

    st.markdown(f"""
    <div class="tr-ph">
        <div class="tr-ph-title">{title}{tag_html}</div>
        {"<div class='tr-ph-sub'>" + subtitle + "</div>" if subtitle else ""}
    </div>
    """, unsafe_allow_html=True)


# ── topbar ────────────────────────────────────────────────────────────────────

def topbar(user: dict, is_gov: bool) -> None:
    """
    Render the top bar: role pill + mode pill + AI status + audit status.
    Government: AI pill reads 'AI off (offline mode)', no YouTube controls rendered.
    """
    from tracerag.audit import AuditLog
    from pathlib import Path
    from config import index_dir as _idx_dir

    role_name = _role_display(user.get("role", "analyst"))
    mode_tone = "offline" if is_gov else "online"
    mode_text = "Offline mode" if is_gov else "Online mode"

    # Audit chain status
    try:
        ok, _ = AuditLog(_idx_dir()).verify_chain()
        audit_text = "Audit chain: verified" if ok else "Audit chain: broken"
        audit_tone = "teal" if ok else "gray"
    except Exception:
        audit_text = "Audit chain: unavailable"
        audit_tone = "gray"

    # AI status
    if is_gov:
        ai_text = "AI off (offline mode)"
        ai_tone = "offline"
    else:
        from study.ai_generate import _can_use_api, _provider
        if _can_use_api():
            ai_text = f"AI ready ({_provider().title()})"
            ai_tone = "teal"
        else:
            ai_text = "AI offline"
            ai_tone = "gray"

    pills_html = (
        pill(role_name, "gray") + " " +
        pill(mode_text, mode_tone) + " " +
        pill(ai_text, ai_tone) + " " +
        pill(audit_text, audit_tone)
    )

    st.markdown(f"""
    <div class="tr-topbar" role="banner">
        <div class="tr-topbar-left"></div>
        <div class="tr-topbar-right">{pills_html}</div>
    </div>
    """, unsafe_allow_html=True)


def _role_display(role: str) -> str:
    return {
        "government":  "Government",
        "analyst":     "Analyst",
        "journalist":  "Journalist",
        "student":     "Student",
        "factchecker": "Fact-checker",
        "auditor":     "Auditor",
    }.get(role.lower(), role.title())


# ── sidebar ───────────────────────────────────────────────────────────────────

# Navigation structure — no emoji, plain text with icon codes
NAV_STRUCTURE = {
    "government": {
        "Workspace": ["Overview", "My PDFs", "Ask a question"],
        "Trust":     ["Audit log"],
    },
    "analyst": {
        "Workspace": ["Overview", "My PDFs", "Ask a question"],
        "Trust":     ["Audit log"],
    },
    "journalist": {
        "Workspace": ["Overview", "My PDFs", "Ask a question"],
        "Trust":     ["Audit log"],
    },
    "student": {
        "Workspace": ["Overview", "My PDFs", "Ask a question"],
        "Study":     ["Flashcards", "Quiz", "Videos"],
        "Trust":     ["Audit log"],
    },
    "factchecker": {
        "Workspace": ["Overview", "My PDFs", "Ask a question"],
        "Trust":     ["Audit log"],
    },
    "auditor": {
        "Workspace": ["Overview", "My PDFs", "Ask a question"],
        "Trust":     ["Audit log", "Users"],
    },
}

# Icon map (Streamlit :material/icon_name: syntax)
_ICONS = {
    "Overview":       ":material/home:",
    "My PDFs":        ":material/folder_open:",
    "Ask a question": ":material/search:",
    "Flashcards":     ":material/style:",
    "Quiz":           ":material/quiz:",
    "Videos":         ":material/play_circle:",
    "Audit log":      ":material/shield:",
    "Users":          ":material/group:",
}


def sidebar_nav(user: dict, is_gov: bool) -> str:
    """
    Render the sidebar and return the selected page name.
    """
    role      = user.get("role", "analyst").lower()
    name      = user.get("name", user.get("username", "User"))
    nav_key   = f"nav_{role}"
    structure = NAV_STRUCTURE.get(role, NAV_STRUCTURE["analyst"])

    # Brand
    st.sidebar.markdown("""
    <div style="padding:1rem 0.75rem 0.75rem;">
        <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.3rem;">
            <div style="width:32px;height:32px;background:#F5B700;border-radius:8px;
                        display:flex;align-items:center;justify-content:center;
                        font-size:16px;flex-shrink:0;">&#10003;</div>
            <span style="font-size:15px;font-weight:800;color:#FFFFFF;letter-spacing:-0.02em;">
                TraceRAG
            </span>
        </div>
        <div style="font-size:11px;color:#475569;padding-left:40px;">
            Evidence intelligence
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Build flat list of all pages for the radio widget
    all_pages = []
    group_labels = {}   # page → group label for display
    for group, pages in structure.items():
        for page in pages:
            all_pages.append(page)
            group_labels[page] = group

    # Render grouped nav labels (decorative separators)
    # Streamlit radio can't have groups, so we use section headers above it
    current_group = None
    section_html  = []
    for page in all_pages:
        g = group_labels[page]
        if g != current_group:
            current_group = g
            section_html.append(
                f'<div class="tr-nav-group">{g}</div>'
            )
        icon = _ICONS.get(page, "")
        section_html.append(
            f'<div style="padding:0 0.25rem 0.1rem;">'
            f'{icon} {page}</div>'
        )

    # Actual radio (hidden label, options are plain page names)
    st.sidebar.markdown("<div style='margin-top:0.5rem;'>", unsafe_allow_html=True)

    # We inject group headers as non-interactive markdown, then use a radio
    # Streamlit doesn't support grouped radio, so we show headers separately
    # and keep the radio hidden-label
    for group, pages in structure.items():
        st.sidebar.markdown(
            f'<div class="tr-nav-group">{group}</div>',
            unsafe_allow_html=True,
        )
        # Mini radio per group
        group_sel = st.sidebar.radio(
            group, pages,
            key=f"{nav_key}_{group}",
            label_visibility="collapsed",
            format_func=lambda p: f"{_ICONS.get(p, '')}  {p}",
        )
        # Store last clicked group selection
        if group_sel:
            st.session_state[nav_key] = group_sel

    st.sidebar.markdown("</div>", unsafe_allow_html=True)

    # User + sign out
    st.sidebar.markdown("<hr/>", unsafe_allow_html=True)
    mode_lbl = "Offline mode" if is_gov else "Online mode"
    st.sidebar.markdown(f"""
    <div style="padding:0.5rem 0.75rem 0.4rem;">
        <div style="font-size:13px;font-weight:700;color:#FFFFFF;">{name}</div>
        <div style="font-size:11px;color:#64748B;">{_role_display(role)}</div>
        <div style="font-size:11px;color:#64748B;">{mode_lbl}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("Sign out", key=f"signout_{role}",
                          use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    return st.session_state.get(nav_key) or all_pages[0]
