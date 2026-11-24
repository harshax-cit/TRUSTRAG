"""
tracerag/role_views.py – Six role dashboards sharing one master UI shell.

Every role uses the SAME layout, sidebar, topbar, cards, and typography.
Only navigation items and page content differ per role.

Master layout:
  Left sidebar  : brand + nav + user profile
  Top bar       : page title + env badge + role badge + username
  Main area     : page-specific content
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from .audit import AuditLog
from .docstore import (
    list_user_documents, delete_document, register_document,
    log_user_activity, get_refusal_ledger, get_verification_stats,
)
from .engine import Engine
from .highlight import render_page_with_highlight
from .ingest import build_index, load_manifest, _file_sha256
from .ui import (
    apply_enterprise_theme, render_sidebar, render_topbar,
    render_top_navbar, render_page_header, page_header,
    stat_row, evidence_box, empty_state, status_badge,
    render_dashboard_metrics, COLORS, ROLE_NAME_MAP,
)
# New design system
try:
    from ui.theme import inject_theme, STATUS_COLORS
    from ui.components import (
        topbar as _topbar, sidebar_nav, page_header as _ph,
        metric_tile, source_chip, empty_state as _empty,
        stepper, progress_bar, badge, pill,
    )
    _NEW_UI = True
except ImportError:
    _NEW_UI = False
from .verify import Verifier

# ── Navigation definitions per role ──────────────────────────────────────────

NAV_ITEMS = {
    "government": [
        ("🏠", "Home"),
        ("📁", "My Documents"),
        ("📤", "Upload"),
        ("❓", "Ask a Question"),
        ("🔍", "Evidence Explorer"),
        ("📊", "Reports"),
        ("🛡️", "Audit Trail"),
        ("⚙️", "Settings"),
    ],
    "analyst": [
        ("🏠", "Home"),
        ("❓", "Ask a Question"),
        ("📁", "My Documents"),
        ("🎬", "Media Library"),
        ("🔍", "Evidence Explorer"),
        ("📊", "Reports"),
        ("🛡️", "Audit Trail"),
        ("⚙️", "Settings"),
        ("❓", "Help"),
    ],
    "journalist": [
        ("🏠", "Home"),
        ("❓", "Ask a Question"),
        ("📁", "My Documents"),
        ("🔍", "Fact-Check"),
        ("📊", "Reports"),
        ("🛡️", "Audit Trail"),
        ("⚙️", "Settings"),
    ],
    "student": [
        ("🏠", "Home"),
        ("📤", "Upload PDF"),
        ("📝", "Summary"),
        ("🃏", "Flashcards"),
        ("🧠", "Quiz"),
        ("▶️", "Videos"),
        ("❓", "Ask a Question"),
        ("📈", "Progress"),
        ("⚙️", "Settings"),
    ],
    "factchecker": [
        ("🏠", "Home"),
        ("🔍", "Fact-Check"),
        ("📁", "My Documents"),
        ("📊", "Evidence Reports"),
        ("🛡️", "Audit Trail"),
        ("⚙️", "Settings"),
    ],
    "auditor": [
        ("🏠", "Home"),
        ("🛡️", "Audit Trail"),
        ("👥", "Users & Roles"),
        ("📊", "Reports"),
        ("📁", "Documents"),
        ("❓", "Ask a Question"),
        ("⚙️", "Settings"),
    ],
}


# ── Master shell ──────────────────────────────────────────────────────────────

def _render_sidebar_brand() -> None:
    """Brand block at the top of every sidebar."""
    st.sidebar.markdown("""
    <div style="padding:0.5rem 0 1rem 0;">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
            <span style="font-size:1.5rem;line-height:1;">🌿</span>
            <span style="font-size:1.2rem;font-weight:800;color:#ffffff;letter-spacing:-0.02em;">TraceRAG</span>
        </div>
        <div style="font-size:0.72rem;color:#64748b;padding-left:0.1rem;line-height:1.3;">
            Multimodal RAG with Explainability
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_sidebar_nav(role: str, nav_key: str) -> str:
    """Render role-specific navigation and return selected page label."""
    items  = NAV_ITEMS.get(role, NAV_ITEMS["analyst"])
    labels = [f"{icon}  {label}" for icon, label in items]

    st.sidebar.markdown(
        "<div style='font-size:0.72rem;font-weight:600;color:#64748b;"
        "text-transform:uppercase;letter-spacing:0.07em;"
        "margin:0.5rem 0 0.4rem 0;'>Navigation</div>",
        unsafe_allow_html=True,
    )
    sel = st.sidebar.radio("nav", labels, key=nav_key,
                            label_visibility="collapsed")
    # sel may be None on the very first render before Streamlit sets a default
    if not sel:
        sel = labels[0]
    return sel.split("  ", 1)[-1] if "  " in sel else sel.strip()


def _render_sidebar_user(user: dict) -> None:
    """User profile and logout at the bottom of the sidebar."""
    st.sidebar.markdown("<hr style='border-color:#1e3a28;margin:0.75rem 0;'/>",
                        unsafe_allow_html=True)
    name = user.get("name", user.get("username", "User"))
    role = user.get("role", "user").replace("factchecker", "Fact-Checker").title()
    st.sidebar.markdown(f"""
    <div style="padding:0.4rem 0 0.5rem 0;">
        <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.2rem;">Signed in as</div>
        <div style="font-size:0.9rem;font-weight:700;color:#ffffff;">{name}</div>
        <div style="font-size:0.75rem;color:#64748b;margin-top:0.15rem;">{role}</div>
    </div>
    """, unsafe_allow_html=True)
    if st.sidebar.button("Sign out", key=f"logout_{user.get('role','x')}",
                          use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


def _master_shell(user: dict, nav_key: str, page_title: str) -> str:
    """
    Render brand + nav + user in sidebar, topbar in main area.
    Returns the selected page name.
    Uses ui.components for the new design system.
    """
    if _NEW_UI:
        from ui.theme import inject_theme
        inject_theme()
        is_gov = user.get("role", "") == "government"
        from ui.components import sidebar_nav, topbar as _topbar
        page = sidebar_nav(user, is_gov)
        _topbar(user, is_gov)
        return page
    # Fallback to old system
    apply_enterprise_theme()
    page = render_sidebar(user, nav_key)
    render_topbar(user, page)
    return page


# ── Shared page implementations ───────────────────────────────────────────────

def _page_home(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    """
    Overview (dashboard) page.
    New design: serif title, metric tiles, continue studying card, topics, recent answers, videos.
    """
    role = user.get("role", "analyst")
    is_gov = role == "government"
    name = user.get("name", "User")

    if _NEW_UI:
        from ui.components import page_header, metric_tile, empty_state, source_chip
        # Determine if we're using demo data
        is_demo = False
        try:
            manifest = load_manifest(str(idx_dir))
            is_demo = any("sample" in k.lower() or "demo" in k.lower() for k in manifest.keys())
        except Exception:
            pass
        
        tag = "Sample data" if is_demo else ""
        page_header("Study overview",
                    "Review your documents, flashcards and recent answers.",
                    tag=tag)
    else:
        render_page_header(
            f"Welcome back, {name.split()[0]}",
            "Search, analyse, and verify information from documents and reports.",
        )

    # Four metric tiles
    try:
        manifest   = load_manifest(str(idx_dir))
        total_docs = len(manifest)
        scanned    = sum(1 for v in manifest.values() if v.get("contains_scans"))
        total_facts= sum(v.get("fact_count", 0) for v in manifest.values())
        # OCR confidence (average across scanned docs)
        ocr_confs  = [v.get("ocr_confidence", 1.0)
                      for v in manifest.values() if v.get("contains_scans")]
        ocr_avg    = sum(ocr_confs) / len(ocr_confs) if ocr_confs else 1.0
        
        audit       = AuditLog(str(idx_dir))
        audit_ok, _ = audit.verify_chain()
        refusals    = len(get_refusal_ledger(str(idx_dir)))
    except Exception:
        total_docs = scanned = total_facts = refusals = 0
        ocr_avg = 1.0
        audit_ok = True

    # Try to get study stats (cards due, quiz average, topics)
    cards_due = 0
    quiz_avg  = 0
    topics_found = 0
    try:
        from study.leitner import get_due_cards
        from study.topics import get_topics
        cards_due = len(get_due_cards())
        topics_found = len(get_topics())
        # Quiz average from session state or storage
        quiz_avg = st.session_state.get("quiz_avg", 0)
    except Exception:
        pass

    if _NEW_UI:
        c1, c2, c3, c4 = st.columns(4)
        metric_tile("Documents",
                    str(total_docs),
                    f"{scanned} scanned · OCR {ocr_avg:.0%}" if scanned else "",
                    col=c1)
        metric_tile("Topics found",
                    str(topics_found),
                    col=c2)
        metric_tile("Cards due today",
                    str(cards_due),
                    col=c3)
        metric_tile("Quiz average",
                    f"{quiz_avg}%" if quiz_avg else "—",
                    col=c4)
    else:
        stat_row([
            {"label": "Documents",     "value": str(total_docs)},
            {"label": "Indexed Facts", "value": f"{total_facts:,}"},
            {"label": "Audit Chain",   "value": "Intact" if audit_ok else "⚠ Broken",
             "color": COLORS["success_text"] if audit_ok else COLORS["danger_text"]},
            {"label": "Refusals",      "value": str(refusals)},
        ])

    st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)

    # Two columns: Continue studying + Topics
    left, right = st.columns([1.2, 1], gap="medium")

    with left:
        st.markdown('<div class="tr-card">', unsafe_allow_html=True)
        st.markdown("**Continue studying**")
        
        # Try to get current flashcard
        current_card = None
        try:
            from study.flashcards import get_next_card
            current_card = get_next_card()
        except Exception:
            pass

        if current_card and _NEW_UI:
            st.markdown(f"""
            <div class="tr-card-navy" style="margin:0.75rem 0;">
                <div class="tr-flashcard-q">{current_card.get('question','')}</div>
                <div style="margin-top:0.75rem;">
                    {source_chip(current_card.get('doc',''), current_card.get('page',1), True)}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("Review again", key="home_card_again"):
                    st.info("Moved to review")
            with b2:
                if st.button("Show answer", key="home_card_flip", type="primary"):
                    st.session_state["show_card_answer"] = True
                    st.rerun()
            with b3:
                if st.button("I knew it", key="home_card_knew"):
                    st.success("Next card")
            
            if st.session_state.get("show_card_answer"):
                st.markdown(f"**Answer:** {current_card.get('answer','')}")
            
            # Deck progress
            if _NEW_UI:
                try:
                    from study.leitner import get_box_counts
                    counts = get_box_counts()
                    total_cards = sum(counts.values())
                    reviewed = sum(counts.get(i,0) for i in [2,3,4,5])
                    pct = reviewed / total_cards if total_cards else 0
                    from ui.components import progress_bar
                    progress_bar(pct, f"Deck progress: {reviewed}/{total_cards}")
                except Exception:
                    pass
        else:
            if _NEW_UI:
                empty_state("No cards yet", "Upload a PDF to generate flashcards")
            else:
                st.info("Upload documents to start studying.")
        
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="tr-card">', unsafe_allow_html=True)
        st.markdown("**Topics**")
        
        try:
            from study.topics import get_topics
            topics = get_topics()
            if topics and _NEW_UI:
                for t in topics[:6]:
                    name = t.get("name", "Unknown")
                    mastery = t.get("mastery", 0)
                    st.markdown(f"""
                    <div style="margin-bottom:0.75rem;">
                        <div style="font-size:13px;font-weight:600;color:#0B1F33;margin-bottom:0.25rem;">
                            {name}
                        </div>
                        <div style="background:#DDE5EC;border-radius:999px;height:6px;overflow:hidden;">
                            <div style="background:#0F7C7E;height:100%;width:{mastery}%;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            elif _NEW_UI:
                empty_state("No topics yet", "Topics are extracted from your documents")
            else:
                st.caption("Topics will appear here")
        except Exception:
            if _NEW_UI:
                empty_state("No topics yet")
            else:
                st.caption("Topics unavailable")
        
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)

    # Bottom row: Recent answers + Videos
    r_left, r_right = st.columns(2, gap="medium")

    with r_left:
        st.markdown('<div class="tr-card">', unsafe_allow_html=True)
        st.markdown("**Recent answers**")
        
        try:
            from tracerag.audit import AuditLog
            log = AuditLog(str(idx_dir))
            entries = log.read_log()[-8:]
            entries.reverse()
            
            if entries and _NEW_UI:
                for e in entries:
                    q = e.get("query", "")[:60]
                    status = e.get("decision", "answer")
                    doc = e.get("source_doc", "")
                    page = e.get("page", 1)
                    receipt = e.get("receipt_id", "")[:12]
                    
                    b_html = badge(status)
                    src_html = source_chip(doc, page, True) if doc else ""
                    
                    st.markdown(f"""
                    <div style="padding:0.5rem 0;border-bottom:1px solid #F4F7FA;">
                        <div style="font-size:13px;font-weight:500;color:#0B1F33;margin-bottom:0.3rem;">
                            {q}
                        </div>
                        <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                            {b_html} {src_html}
                            <span style="font-size:11px;color:#5B6878;" title="Receipt ID">{receipt}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            elif _NEW_UI:
                empty_state("No answers yet", "Ask your first question to see it here")
            else:
                st.caption("No recent answers")
        except Exception as e:
            if _NEW_UI:
                empty_state("Audit log unavailable")
            else:
                st.caption(f"Error: {e}")
        
        st.markdown('</div>', unsafe_allow_html=True)

    with r_right:
        st.markdown('<div class="tr-card">', unsafe_allow_html=True)
        st.markdown("**Recommended videos**")
        
        if is_gov:
            st.caption("Videos unavailable in offline mode")
        else:
            try:
                from study.topics import get_topics
                topics = get_topics()
                if topics and _NEW_UI:
                    for t in topics[:3]:
                        name = t.get("name", "")
                        st.markdown(f"""
                        <div style="padding:0.5rem 0;border-bottom:1px solid #F4F7FA;">
                            <div style="font-size:13px;font-weight:600;color:#0B1F33;">{name}</div>
                            <a href="https://www.youtube.com/results?search_query={name.replace(' ','+')}"
                               target="_blank" style="font-size:12px;color:#0F7C7E;text-decoration:none;">
                                Search YouTube for this topic &rarr;
                            </a>
                        </div>
                        """, unsafe_allow_html=True)
                    st.caption("External recommendations, not verified against your document.")
                elif _NEW_UI:
                    empty_state("No topics yet", "Topics are extracted from uploaded documents")
                else:
                    st.caption("Topics unavailable")
            except Exception:
                if _NEW_UI:
                    empty_state("Topics unavailable")
                else:
                    st.caption("Error loading topics")
        
        st.markdown('</div>', unsafe_allow_html=True)
def _nav_label(role: str, page: str) -> str:
    """Find the full nav label (icon + name) for a page name."""
    items = NAV_ITEMS.get(role, [])
    for icon, label in items:
        if page.lower() in label.lower():
            return f"{icon}  {label}"
    return ""


def _page_ask_question(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    render_page_header(
        "Ask a Question",
        "Every answer is grounded in source documents with page-level evidence.",
        "❓",
    )

    q = st.text_area(
        "Your question",
        placeholder="e.g. What was India's GDP growth rate in FY24?",
        height=90,
        key="ask_q_input",
    )

    col_ask, col_strict = st.columns([3, 1])
    with col_ask:
        ask_btn = st.button("Search & Verify ▶", type="primary",
                             use_container_width=True, key="ask_btn")
    with col_strict:
        strict = st.toggle("Strict mode", key="ask_strict")

    if ask_btn and q.strip():
        with st.spinner("Searching documents and verifying evidence…"):
            try:
                engine = Engine(str(idx_dir), str(pdf_dir))
                result = engine.answer(f"ui_{int(time.time())}", q.strip(),
                                       strict=strict)
            except Exception as e:
                st.error(f"Engine error: {e}")
                return

        status  = result.get("status", "refuse")
        answer  = result.get("answer", "")
        docs    = result.get("doc")
        pages   = result.get("page")
        bbox    = result.get("bbox")
        receipt = result.get("audit_receipt", "")

        if isinstance(docs,  list): docs  = docs[0]  if docs  else None
        if isinstance(pages, list): pages = pages[0] if pages else None
        if isinstance(bbox, str):
            try: bbox = json.loads(bbox)
            except Exception: bbox = None

        # Answer card
        st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)
        badge = status_badge(status)

        if status == "refuse":
            st.warning(
                f"**Not found in collection** {badge}  \n"
                f"Reason: `{', '.join(result.get('reason_codes', ['unknown']))}`"
            )
        elif status == "conflict":
            st.warning(f"**Conflicting values detected** {badge}")
            answers = answer if isinstance(answer, list) else [answer]
            for a in answers:
                st.markdown(f"- {a}")
        else:
            st.markdown(f"""
            <div class="tr-card" style="border-left:3px solid #16a34a;">
                <div style="font-size:0.75rem;font-weight:600;color:#15803d;
                            text-transform:uppercase;letter-spacing:0.05em;
                            margin-bottom:0.5rem;">Answer {badge}</div>
                <div style="font-size:1.1rem;font-weight:600;color:#111827;">
                    {answer}
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Evidence
        ev = result.get("evidence", "")
        if ev and isinstance(ev, str) and len(ev) > 10:
            evidence_box(ev[:400], docs or "—", pages or 0, status)

        # Source page image
        if docs and pages and pdf_dir:
            pdf_path = pdf_dir / docs
            if not pdf_path.exists():
                pdf_path = Path("data/raw/pdfs") / docs
            if pdf_path.exists():
                st.markdown(f"**Source:** `{docs}` — Page **{pages}**")
                try:
                    img = render_page_with_highlight(str(pdf_path), pages, bbox, dpi=130)
                    if img:
                        st.image(img, use_container_width=True)
                except Exception:
                    pass

        if receipt:
            st.caption(f"Receipt: `{receipt}`")

    elif not q.strip() and ask_btn:
        st.warning("Please enter a question.")


def _page_documents(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    render_page_header("Document Library", "Manage and search your documents.", "📁")

    role   = user.get("role", "analyst")
    is_gov = role == "government"

    col_search, col_upload = st.columns([3, 1])
    with col_search:
        search = st.text_input("Search documents", placeholder="Filter by filename…",
                                label_visibility="collapsed", key="doc_search")
    with col_upload:
        upload_btn = st.button("+ Upload", type="primary",
                                use_container_width=True, key="doc_upload_btn")

    if upload_btn:
        st.session_state[f"nav_{role}"] = _nav_label(role, "Upload") or \
            _nav_label(role, "Upload PDF")
        st.rerun()

    # Upload widget in-page
    with st.expander("📤 Upload a new document", expanded=False):
        _inline_upload(user, idx_dir, pdf_dir)

    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)

    docs = list_user_documents(user["username"], role, is_government=is_gov,
                                search_query=search if search else None)
    if not docs:
        empty_state("No documents found",
                    "Upload a PDF to begin analysis." if not search
                    else "No documents match your search.", "📄")
        return

    for d in docs:
        with st.container(border=True):
            c1, c2, c3 = st.columns([6, 2, 2])
            with c1:
                ext  = d.get("file_type", "pdf").upper()
                size = round(d.get("file_size", 0) / 1024, 1)
                facts= d.get("fact_count", 0)
                ts   = d.get("upload_time", "")[:16].replace("T", " ")
                st.markdown(
                    f"**{d['filename']}** "
                    f"<span class='tr-badge tr-badge-gray'>{ext}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"{size} KB · {facts} facts · {ts}")
            with c2:
                status_cls = "tr-badge-green" if d.get("status") == "ready" else "tr-badge-amber"
                status_lbl = "✅ Ready" if d.get("status") == "ready" else "⏳ Processing"
                st.markdown(
                    f"<div style='padding-top:0.6rem;'>"
                    f"<span class='tr-badge {status_cls}'>{status_lbl}</span></div>",
                    unsafe_allow_html=True,
                )
            with c3:
                if st.button("🗑 Delete", key=f"del_{d['doc_id']}",
                              use_container_width=True):
                    delete_document(d["doc_id"], user["username"], role, is_gov)
                    st.success(f"Deleted {d['filename']}.")
                    st.rerun()


def _inline_upload(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    """Compact upload panel reused on the Documents page."""
    from study.upload import (
        new_session_id, session_dirs, validate_pdf, save_upload,
        ingest_session_pdf, sha256_of, UploadError, MAX_UPLOAD_MB, MAX_PAGES,
    )
    st.caption(f"Max {MAX_UPLOAD_MB} MB · {MAX_PAGES} pages · PDF only")
    uf = st.file_uploader("Choose PDF", type=["pdf"], key="inline_uploader")
    if uf and st.button("Index document", type="primary", key="inline_index"):
        data = uf.read()
        try:
            validate_pdf(data, uf.name)
        except UploadError as e:
            st.error(str(e))
            return
        prog = st.progress(0.2, text="Saving…")
        dest = pdf_dir / uf.name
        pdf_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        sha = _file_sha256(str(dest))
        prog.progress(0.5, text="Indexing…")
        try:
            import logging
            logging.getLogger("tracerag.ingest").setLevel(logging.WARNING)
            build_index(str(pdf_dir), str(idx_dir))
            register_document(uf.name, user["username"], user.get("role", "analyst"),
                               sha, len(data), "pdf",
                               is_government=(user.get("role") == "government"))
            prog.progress(1.0, text="Done!")
            st.success(f"✅ **{uf.name}** indexed successfully.")
        except Exception as e:
            st.error(f"Indexing failed: {e}")


def _page_evidence_explorer(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    render_page_header("Evidence Explorer",
                        "Browse extracted facts, tables, charts, and bounding boxes.", "🔍")

    db = idx_dir / "facts.db"
    if not db.exists():
        empty_state("No index available",
                    "Build the index first with `python run.py build`.", "🗄️")
        return

    conn = sqlite3.connect(str(db), check_same_thread=False)

    col_a, col_b, col_c = st.columns([2, 2, 1])
    with col_a:
        docs_in_db = conn.execute("SELECT DISTINCT doc FROM facts").fetchall()
        doc_names  = ["All documents"] + [r[0] for r in docs_in_db]
        sel_doc    = st.selectbox("Document", doc_names, key="ev_doc")
    with col_b:
        kind_opts  = ["All types", "sentence", "table_cell", "chart_label", "ocr_row"]
        sel_kind   = st.selectbox("Fact type", kind_opts, key="ev_kind")
    with col_c:
        keyword    = st.text_input("Keyword", placeholder="Filter…", key="ev_kw",
                                    label_visibility="visible")

    # Build query
    clauses, params = [], []
    if sel_doc != "All documents":
        clauses.append("doc=?"); params.append(sel_doc)
    if sel_kind != "All types":
        clauses.append("kind=?"); params.append(sel_kind)
    if keyword:
        clauses.append("raw_text LIKE ?"); params.append(f"%{keyword}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = conn.execute(
        f"SELECT doc,page,kind,value,unit,period,bbox,raw_text "
        f"FROM facts {where} ORDER BY doc,page LIMIT 200",
        params
    ).fetchall()
    conn.close()

    if not rows:
        empty_state("No facts match", "Try different filters.", "🔍")
        return

    st.caption(f"Showing {len(rows)} facts (max 200)")
    df = pd.DataFrame(rows, columns=["Document","Page","Kind","Value","Unit","Period","BBox","Raw Text"])
    df["Raw Text"] = df["Raw Text"].str[:80]
    df["BBox"]     = df["BBox"].apply(lambda b: "✓" if b else "")
    st.dataframe(df[["Document","Page","Kind","Value","Unit","Period","BBox","Raw Text"]],
                 use_container_width=True, hide_index=True)

    # Page viewer
    st.markdown("#### View Source Page")
    sel_row_doc  = st.selectbox("Document", [r[0] for r in rows], key="ev_view_doc")
    sel_row_page = st.number_input("Page", min_value=1, value=1, key="ev_view_page")
    if st.button("Load page", key="ev_load"):
        pdf_path = pdf_dir / sel_row_doc
        if not pdf_path.exists():
            pdf_path = Path("data/raw/pdfs") / sel_row_doc
        if pdf_path.exists():
            try:
                img = render_page_with_highlight(str(pdf_path), int(sel_row_page),
                                                  dpi=130)
                st.image(img, use_container_width=True)
            except Exception as e:
                st.error(str(e))
        else:
            st.warning("PDF not found.")


def _page_reports(user: dict, idx_dir: Path) -> None:
    render_page_header("Reports & Analysis",
                        "Cross-document comparisons, metric trends, and conflict detection.", "📊")

    db = idx_dir / "facts.db"
    if not db.exists():
        empty_state("No data available", "Build the index first.", "📊")
        return

    tab_trends, tab_conflicts = st.tabs(["📈 Metric Trends", "⚔️ Conflicts"])

    with tab_trends:
        conn = sqlite3.connect(str(db), check_same_thread=False)
        # Units available
        units = [r[0] for r in conn.execute(
            "SELECT DISTINCT unit FROM facts WHERE unit!='' ORDER BY unit").fetchall()]
        sel_unit = st.selectbox("Select metric unit", ["per cent", "crore", "million"] + units,
                                 key="rep_unit")
        rows = conn.execute(
            "SELECT doc, period, value, value_num, page FROM facts "
            "WHERE unit=? AND period IS NOT NULL AND value_num IS NOT NULL "
            "ORDER BY period, doc LIMIT 100",
            (sel_unit,)
        ).fetchall()
        conn.close()
        if rows:
            df = pd.DataFrame(rows, columns=["Document","Period","Value","Value (num)","Page"])
            df["Document"] = df["Document"].str[-35:]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            empty_state("No data", f"No facts found with unit '{sel_unit}'.")

    with tab_conflicts:
        conn = sqlite3.connect(str(db), check_same_thread=False)
        # Find values with same period but different values across docs
        conflicts = conn.execute("""
            SELECT a.period, a.unit, a.doc, a.value, a.page,
                   b.doc, b.value, b.page
            FROM facts a JOIN facts b
            ON a.period = b.period AND a.unit = b.unit
            AND a.doc != b.doc
            AND a.value_num IS NOT NULL AND b.value_num IS NOT NULL
            AND ABS(a.value_num - b.value_num) / (ABS(a.value_num) + 0.001) > 0.005
            WHERE a.unit IN ('per cent','crore','million')
            ORDER BY a.period
            LIMIT 50
        """).fetchall()
        conn.close()
        if conflicts:
            df = pd.DataFrame(conflicts,
                columns=["Period","Unit","Doc A","Value A","Page A",
                         "Doc B","Value B","Page B"])
            df["Doc A"] = df["Doc A"].str[-30:]
            df["Doc B"] = df["Doc B"].str[-30:]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.success("✅ No significant conflicts detected in the current collection.")


def _page_audit_trail(user: dict, idx_dir: Path) -> None:
    render_page_header("Audit Trail",
                        "HMAC-SHA256 chain log — tamper-evident record of all actions.", "🛡️")

    audit = AuditLog(str(idx_dir))
    ok, msg = audit.verify_chain()

    if ok:
        st.success(f"🔒 **Chain Intact** — {msg}")
    else:
        st.error(f"💥 **Chain BROKEN** — {msg}")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### Decision Mix")
        mix = audit.get_decision_mix()
        if any(mix.values()):
            df_mix = pd.DataFrame(
                [{"Status": k.title(), "Count": v} for k, v in mix.items() if v > 0]
            )
            st.bar_chart(df_mix.set_index("Status"))
        else:
            empty_state("No decisions yet", "", "📊")

    with c2:
        st.markdown("#### Refusal Ledger")
        ledger = get_refusal_ledger(str(idx_dir))
        if ledger:
            df_l = pd.DataFrame([{
                "ID":     r.get("question_id",""),
                "Reason": r.get("reason",""),
                "Time":   r.get("ts","")[:19],
            } for r in ledger[-20:]])
            st.dataframe(df_l, use_container_width=True, hide_index=True)
        else:
            empty_state("No refusals logged", "", "✅")

    # Tamper demo
    st.markdown("#### 🔧 Tamper Detection Demo")
    st.caption(
        "Creates a **copy** of the log, edits one record, and shows the chain breaking. "
        "The original log is never modified."
    )
    if st.button("Run tamper demo", key="audit_tamper"):
        demo_dir = str(idx_dir / "tamper_demo")
        with st.spinner("Running…"):
            res = audit.tamper_demo(demo_dir)
        col_orig, col_tamp = st.columns(2)
        with col_orig:
            st.markdown("**Original**")
            if res.get("original_chain_ok"):
                st.success("✅ Chain intact")
            else:
                st.error("💥 Broken")
            st.caption(res.get("original_message",""))
        with col_tamp:
            st.markdown("**Tampered copy**")
            if res.get("tampered_chain_ok"):
                st.error("⚠️ Not detected (unexpected)")
            else:
                st.error("💥 Tamper detected!")
            st.caption(res.get("tampered_message",""))
        st.info(res.get("note",""))

    # Export
    st.markdown("#### Export")
    if st.button("Export JSONL", key="audit_export"):
        import tempfile, shutil
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            n = audit.export_jsonl(tmp.name)
            data = open(tmp.name, "rb").read()
        st.download_button(f"Download ({n} records)", data,
                           "audit_export.jsonl", "application/json")


def _page_settings(user: dict, idx_dir: Path) -> None:
    render_page_header("Settings", "Account and application preferences.", "⚙️")

    st.markdown("#### Account")
    with st.container(border=True):
        st.markdown(f"**Username:** `{user.get('username', '—')}`")
        st.markdown(f"**Name:** {user.get('name', '—')}")
        st.markdown(f"**Role:** {user.get('role', '—').title()}")
        st.markdown(f"**Environment:** {'🔒 Offline (Government)' if user.get('offline') else '🌐 Online'}")

    st.markdown("#### Index")
    with st.container(border=True):
        try:
            m = load_manifest(str(idx_dir))
            total = sum(v.get("fact_count",0) for v in m.values())
            st.markdown(f"**PDFs indexed:** {len(m)}  \n**Total facts:** {total:,}")
        except Exception:
            st.info("Index not built yet.")
        if st.button("Rebuild index", key="settings_rebuild"):
            st.warning("Run `python run.py build <pdf_dir>` from the CLI to rebuild the index.")


def _page_help(user: dict) -> None:
    render_page_header("Help & Support", "Documentation and usage guides.", "❓")
    st.markdown("""
    #### Getting Started
    1. **Upload** a PDF via My Documents or the Upload page
    2. **Ask a Question** — the system finds and verifies the answer
    3. **Evidence Explorer** — browse extracted facts with source pages
    4. **Audit Trail** — verify the tamper-evident log

    #### Supported document types
    - PDF (text layer, scanned via OCR, tables, charts)
    - Scanned PDFs are processed automatically with Tesseract OCR

    #### Answer statuses
    - ✅ **Verified** — answer found and confirmed in source document
    - ⚠️ **Conflict** — two sources report different values
    - ❌ **Not Found** — no evidence in the collection

    #### Offline mode (Government)
    All processing runs locally. No data is sent to external services.

    #### Support
    Repository: [github.com/harshax-cit/TRUSTRAG](https://github.com/harshax-cit/TRUSTRAG)
    """)


def _page_factcheck(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    render_page_header("Fact-Checker",
                        "Paste any claim — the system classifies it as Supported, Contradicted, or Not Found.",
                        "🔍")

    claim = st.text_area("Claim to verify",
                          placeholder="e.g. India's GDP growth was 8.2% in FY24",
                          height=100, key="fc_claim")
    if st.button("Check claim", type="primary", key="fc_check") and claim.strip():
        with st.spinner("Verifying…"):
            try:
                engine = Engine(str(idx_dir), str(pdf_dir))
                result = engine.answer(f"fc_{int(time.time())}", claim.strip())
            except Exception as e:
                st.error(str(e)); return

        status = result.get("status","refuse")
        answer = result.get("answer","")
        docs   = result.get("doc")
        pages  = result.get("page")
        if isinstance(docs,  list): docs  = docs[0]  if docs  else None
        if isinstance(pages, list): pages = pages[0] if pages else None

        import re
        claim_nums  = re.findall(r"\b\d+\.?\d*\b", claim)
        answer_nums = re.findall(r"\b\d+\.?\d*\b", str(answer))
        def close(a,b):
            try: return abs(float(a)-float(b))/(abs(float(b))+1e-9) <= 0.02
            except: return False

        if status == "refuse":
            st.info("⚪ **Not in collection** — cannot confirm or contradict.")
        elif status == "conflict":
            st.warning(f"🟡 **Conflicting sources** — found: {answer}")
        elif claim_nums and answer_nums and any(
                close(cn,an) for cn in claim_nums for an in answer_nums):
            st.success(f"✅ **Supported** — collection reports **{answer}** "
                       f"(Source: {docs}, p.{pages})")
        else:
            st.error(f"❌ **Contradicted** — collection reports **{answer}** "
                     f"(Source: {docs}, p.{pages})")

        ev = result.get("evidence","")
        if ev and isinstance(ev, str) and len(ev) > 10:
            evidence_box(ev[:300], docs or "—", pages or 0, status)


def _page_media_library(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    render_page_header("Media Library",
                        "Browse extracted tables, charts, and scanned pages.", "🎬")

    db = idx_dir / "facts.db"
    if not db.exists():
        empty_state("No index available", "Build the index first.", "🗄️")
        return

    conn = sqlite3.connect(str(db), check_same_thread=False)
    tab_tables, tab_charts, tab_scans = st.tabs(
        ["📊 Tables", "📈 Charts", "🖼️ Scanned Pages"])

    with tab_tables:
        rows = conn.execute(
            "SELECT doc,page,metric,entity,value,unit,period "
            "FROM facts WHERE kind='table_cell' AND value_num IS NOT NULL "
            "ORDER BY doc,page LIMIT 200"
        ).fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["Doc","Page","Metric","Entity","Value","Unit","Period"])
            df["Doc"] = df["Doc"].str[-30:]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            empty_state("No table facts", "Process PDFs with tables first.")

    with tab_charts:
        rows = conn.execute(
            "SELECT doc,page,metric,value,unit,period "
            "FROM facts WHERE kind='chart_label' AND value_num IS NOT NULL "
            "ORDER BY doc,page LIMIT 200"
        ).fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["Doc","Page","Chart","Value","Unit","Period"])
            df["Doc"] = df["Doc"].str[-30:]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            empty_state("No chart labels", "Process PDFs with charts first.")

    with tab_scans:
        rows = conn.execute(
            "SELECT doc,page,confidence FROM regions "
            "WHERE kind='scanned_page' ORDER BY doc,page"
        ).fetchall() if _table_exists(conn, "regions") else []
        if rows:
            df = pd.DataFrame(rows, columns=["Doc","Page","OCR Confidence"])
            df["Doc"] = df["Doc"].str[-30:]
            df["OCR Confidence"] = df["OCR Confidence"].apply(lambda c: f"{c:.0%}")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            empty_state("No scanned pages", "Upload a scanned PDF to see OCR results.")

    conn.close()


def _table_exists(conn, name: str) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return r is not None


def _page_users(user: dict) -> None:
    render_page_header("Users & Roles",
                        "Manage user accounts and role assignments. Admin only.", "👥")
    from auth import _load_users
    users = _load_users()
    rows = [{"Username": u, "Name": v.get("name",""), "Role": v.get("role","")}
            for u, v in users.items()]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("To add accounts, edit `TRACERAG_USERS_FILE` or update auth.py.")


# ── Student study pages (delegated to study module) ───────────────────────────

def _page_student_upload() -> None:
    from app import study_tab_upload
    study_tab_upload()

def _page_student_summary() -> None:
    from app import study_tab_summary
    study_tab_summary()

def _page_student_flashcards() -> None:
    from app import study_tab_flashcards
    study_tab_flashcards()

def _page_student_quiz() -> None:
    from app import study_tab_quiz
    study_tab_quiz()

def _page_student_videos() -> None:
    from app import study_tab_videos
    study_tab_videos()

def _page_student_progress() -> None:
    from app import study_tab_progress
    study_tab_progress()


# ── Six role entry points ─────────────────────────────────────────────────────

def render_government_interface(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    page = _master_shell(user, "nav_government", "Government Secure Workspace")
    _dispatch_page(page, user, idx_dir, pdf_dir)


def render_analyst_interface(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    page = _master_shell(user, "nav_analyst", "Policy Analyst Workspace")
    _dispatch_page(page, user, idx_dir, pdf_dir)


def render_journalist_interface(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    page = _master_shell(user, "nav_journalist", "Journalist Workspace")
    _dispatch_page(page, user, idx_dir, pdf_dir)


def render_student_dashboard(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    page = _master_shell(user, "nav_student", "Student Study Workspace")
    _dispatch_page(page, user, idx_dir, pdf_dir)


def render_factchecker_interface(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    page = _master_shell(user, "nav_factchecker", "Fact-Checker Workspace")
    _dispatch_page(page, user, idx_dir, pdf_dir)


def render_auditor_dashboard(user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    page = _master_shell(user, "nav_auditor", "Auditor / Admin Workspace")
    _dispatch_page(page, user, idx_dir, pdf_dir)


def _dispatch_page(page: str, user: dict, idx_dir: Path, pdf_dir: Path) -> None:
    """
    Single unified dispatch for all roles.
    Maps new nav page names AND legacy names to their handler functions.
    """
    # Import study tabs lazily to avoid circular imports
    import app as _app

    dispatch = {
        # New nav names
        "Overview":        lambda: _page_home(user, idx_dir, pdf_dir),
        "My PDFs":         lambda: _page_documents(user, idx_dir, pdf_dir),
        "Ask a question":  lambda: _page_ask_question(user, idx_dir, pdf_dir),
        "Flashcards":      _app.study_tab_flashcards,
        "Quiz":            _app.study_tab_quiz,
        "Videos":          _app.study_tab_videos,
        "Audit log":       lambda: _page_audit_trail(user, idx_dir),
        "Users":           lambda: _page_users(user),
        # Legacy names (kept for backward compat)
        "Home":            lambda: _page_home(user, idx_dir, pdf_dir),
        "My Documents":    lambda: _page_documents(user, idx_dir, pdf_dir),
        "Upload":          lambda: _page_documents(user, idx_dir, pdf_dir),
        "Upload PDF":      _app.study_tab_upload,
        "Ask a Question":  lambda: _page_ask_question(user, idx_dir, pdf_dir),
        "Evidence Explorer": lambda: _page_evidence_explorer(user, idx_dir, pdf_dir),
        "Reports":         lambda: _page_reports(user, idx_dir),
        "Audit Trail":     lambda: _page_audit_trail(user, idx_dir),
        "Fact-Check":      lambda: _page_factcheck(user, idx_dir, pdf_dir),
        "Media Library":   lambda: _page_media_library(user, idx_dir, pdf_dir),
        "Summary":         _app.study_tab_summary,
        "Progress":        _app.study_tab_progress,
        "Settings":        lambda: _page_settings(user, idx_dir),
        "Help":            lambda: _page_help(user),
        "Evidence Reports":lambda: _page_reports(user, idx_dir),
    }
    fn = dispatch.get(page or "Overview")
    if fn:
        fn()
    else:
        _page_home(user, idx_dir, pdf_dir)
