"""
app.py – TraceRAG Streamlit UI

Role-based hybrid deployment:
  Government (GOVERNMENT_MODE=offline) → offline dashboard, local only
  All other roles                      → online dashboard

Five original lenses + 7 Study Mode tabs are preserved unchanged.
Login screen routes each role to its authorised tabs.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from tracerag.educational import generate_student_materials, summarize_document
from tracerag.role_views import (
    render_government_interface,
    render_analyst_interface,
    render_journalist_interface,
    render_student_dashboard,
    render_factchecker_interface,
    render_auditor_dashboard,
)
from tracerag.system_status import render_system_status_page

# ── config & auth (imported first so government guard activates early) ────────
from config import (
    is_government_mode, get_mode_label, get_ai_label,
    index_dir as _cfg_index_dir, pdf_dir as _cfg_pdf_dir,
    ROLE_TABS, GovernmentModeViolation,
)
from auth import authenticate, get_role_info, is_authorised, AuthError
from tracerag.ui import apply_enterprise_theme, render_top_navbar, render_dashboard_metrics
from tracerag.docstore import (
    register_document, list_user_documents, get_document,
    delete_document, update_document_status
)
from tracerag.compare import compare_documents, analyze_metric_trend
from tracerag.multimodal import (
    ingest_csv_facts, ingest_image_facts, ingest_video_facts
)

# ── paths (environment-aware) ─────────────────────────────────────────────────
ROOT      = Path(__file__).parent
INDEX_DIR = Path(_cfg_index_dir())
PDF_DIR   = Path(_cfg_pdf_dir())
QUESTIONS = ROOT / "data" / "raw" / "practice_questions.jsonl"
ANSWERS   = ROOT / "data" / "raw" / "practice_answers.jsonl"

# ── lazy imports ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    from tracerag.engine import Engine
    return Engine(str(INDEX_DIR), str(PDF_DIR))

@st.cache_resource
def get_audit():
    from tracerag.audit import AuditLog
    return AuditLog(str(INDEX_DIR))

def db_conn():
    """Thread-safe SQLite connection."""
    db = INDEX_DIR / "facts.db"
    if not db.exists():
        return None
    return sqlite3.connect(str(db), check_same_thread=False)

# ── helpers ───────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    items = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    return items

def render_page_bytes(doc_name: str, page_num: int,
                      bbox=None, dpi: int = 130) -> Optional[bytes]:
    """Render a PDF page to PNG bytes with optional highlight."""
    pdf_path = PDF_DIR / doc_name
    if not pdf_path.exists():
        return None
    try:
        from tracerag.highlight import render_page_with_highlight
        return render_page_with_highlight(str(pdf_path), page_num, bbox, dpi=dpi)
    except Exception as e:
        st.warning(f"Cannot render page: {e}")
        return None

def status_badge(status: str) -> str:
    colours = {"answer": "🟢", "conflict": "🟡", "refuse": "🔴"}
    return colours.get(status, "⚪")

def journalist_badge(status: str) -> str:
    if status == "answer":
        return "🟢 **VERIFIED** — Safe to publish"
    if status == "conflict":
        return "🟡 **PROVISIONAL** — Conflicting sources, verify before publishing"
    return "🔴 **NOT FOUND** — Do not publish without independent verification"

def ask(question: str, strict: bool = False) -> dict:
    engine = get_engine()
    qid = f"ui_{int(time.time()*1000)}"
    return engine.answer(qid, question, strict=strict)

def _page_list(result: dict) -> list[int]:
    p = result.get("page")
    if isinstance(p, list):
        return [x for x in p if x is not None]
    return [p] if p else []

def _doc_list(result: dict) -> list[str]:
    d = result.get("doc")
    if isinstance(d, list):
        return [x for x in d if x is not None]
    return [d] if d else []

# ── sidebar ───────────────────────────────────────────────────────────────────

def sidebar():
    apply_enterprise_theme()
    st.sidebar.markdown(
        """
        <div style="padding: 0.25rem 0 0.85rem 0;">
            <div style="display:flex; align-items:center; gap:0.5rem;">
                <span style="font-size:1.6rem;">🌿</span>
                <span style="font-size:1.35rem; font-weight:700; color:#ffffff; letter-spacing:-0.02em;">TraceRAG</span>
            </div>
            <div style="font-size:0.75rem; color:#94a3b8; margin-top:2px;">Multimodal Evidence Intelligence</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Enterprise Navigation ─────────────────────────────────────────────────
    nav_options = [
        "🏠 Home",
        "❓ Ask a Question",
        "📁 My Documents",
        "🎬 Media Library",
        "🔍 Evidence Explorer",
        "📊 Reports & Comparisons",
        "🛡️ Audit Trail",
        "⚙️ Settings",
        "❓ Help & Support",
    ]
    st.sidebar.radio("Navigation", nav_options, key="enterprise_nav", label_visibility="collapsed")
    st.sidebar.markdown("<hr style='border-color:#1c4532; margin:0.6rem 0;' />", unsafe_allow_html=True)

    # ── Environment indicator ─────────────────────────────────────────────────
    if is_government_mode():
        st.sidebar.error(
            "🔒 **OFFLINE SECURE**\n\n"
            "Government Local Isolated Environment. External network is strictly disabled."
        )
    else:
        ai_label = get_ai_label()
        st.sidebar.info(f"{get_mode_label()}\n\n{ai_label}")

    # ── Logged-in user info ───────────────────────────────────────────────────
    user = st.session_state.get("user")
    if user:
        role_info = get_role_info(user["role"])
        st.sidebar.success(
            f"{role_info['icon']} **{user['name']}**\n\n"
            f"Role: {role_info['label']}"
        )
        if st.sidebar.button("Logout", width="stretch"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    st.sidebar.markdown("<hr style='border-color:#1c4532; margin:0.6rem 0;' />", unsafe_allow_html=True)
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:600; color:#cbd5e1; margin-bottom:0.4rem;'>QUICK QUERY</div>", unsafe_allow_html=True)

    # ── Dev mode toggle (online users only, doesn't touch audit chain) ────────
    _user = st.session_state.get("user", {})
    if _user and not _user.get("offline", False):
        with st.sidebar.expander("🔧 Dev Options", expanded=False):
            st.caption("Toggles API access for this session only. Audit chain is never modified.")
            _force_off = st.toggle(
                "Block all external APIs",
                value=(os.environ.get("EXTERNAL_API_ENABLED","true").lower() == "false"),
                key="dev_force_offline",
            )
            if _force_off:
                os.environ["EXTERNAL_API_ENABLED"] = "false"
                os.environ["AI_PROVIDER"] = "local"
                st.caption("🔒 External APIs blocked for this session.")
            else:
                os.environ["EXTERNAL_API_ENABLED"] = "true"
                os.environ["AI_PROVIDER"] = os.environ.get("AI_PROVIDER", "cloud")

    # Quick question selector (must be first selectbox for test_app.py)
    questions = load_jsonl(QUESTIONS)
    options   = ["— custom question —"] + [q["question"][:80] for q in questions]
    sel    = st.sidebar.selectbox("Practice questions", options)
    custom = st.sidebar.text_area("Or type your question", height=80)

    if sel != "— custom question —":
        q_text = next(q["question"] for q in questions if q["question"][:80] == sel)
    else:
        q_text = custom.strip()

    run    = st.sidebar.button("Ask ▶", type="primary", width="stretch")
    strict = st.sidebar.toggle("Strict mode (6-field output)")
    return q_text, run, strict

# ── LENS 1: Analyst ───────────────────────────────────────────────────────────

def lens_analyst(result: dict, question: str):
    st.subheader("📊 Analyst View")

    status = result.get("status", "")
    st.markdown(f"**Status:** {status_badge(status)} `{status.upper()}`")

    if status == "refuse":
        st.error("No verifiable answer found in the document collection.")
        codes = result.get("reason_codes", [])
        if codes:
            st.markdown(f"**Reason:** `{', '.join(codes)}`")
        nearest = result.get("evidence", "")
        if nearest:
            with st.expander("Nearest evidence found"):
                st.write(nearest)
        return

    # ── conflict: side-by-side ───────────────────────────────────────────────
    if status == "conflict":
        st.warning("⚠️ **Conflict detected** — two sources report different values.")
        evidence = result.get("evidence", {})
        values = evidence.get("values", []) if isinstance(evidence, dict) else []
        if len(values) == 2:
            col1, col2 = st.columns(2)
            for col, v in zip([col1, col2], values):
                with col:
                    st.markdown(f"**{v.get('doc','')[:40]}**")
                    st.metric("Value", v.get("value", ""))
                    pg = v.get("page") or v.get("pg")
                    if pg:
                        st.caption(f"Page {pg}")
                    img = render_page_bytes(v.get("doc",""), pg or 1,
                                            v.get("bbox"))
                    if img:
                        st.image(img, width="stretch")

        # Revision timeline
        st.markdown("#### 📅 Revision Timeline")
        docs = _doc_list(result)
        pages = _page_list(result)
        answers = result.get("answer", [])
        if isinstance(answers, list) and docs:
            timeline_rows = []
            for i, (d, p, a) in enumerate(zip(docs, pages,
                                               answers if isinstance(answers, list)
                                               else [answers])):
                yr = "".join(c for c in d if c.isdigit())[:4] or str(2023 + i)
                timeline_rows.append({"Document": d, "Page": p,
                                       "Value": a, "Year": yr})
            st.dataframe(pd.DataFrame(timeline_rows), width="stretch")
        return

    # ── normal answer ────────────────────────────────────────────────────────
    st.success(f"**Answer:** {result.get('answer', '')}")

    docs  = _doc_list(result)
    pages = _page_list(result)
    bbox  = result.get("bbox")
    if isinstance(bbox, str):
        try:
            bbox = json.loads(bbox)
        except Exception:
            bbox = None

    if docs and pages:
        st.markdown(f"**Source:** `{docs[0]}` — Page **{pages[0]}**")
        img = render_page_bytes(docs[0], pages[0], bbox)
        if img:
            st.image(img, caption=f"Page {pages[0]} (highlighted)", width="stretch")

    # Evidence
    ev = result.get("evidence", "")
    if ev:
        with st.expander("Evidence text"):
            st.write(ev)

    # Confidence
    conf = result.get("confidence")
    if conf is not None:
        st.progress(float(conf), text=f"Confidence: {conf:.0%}")

    # Brief basket / CSV export
    st.markdown("#### 📥 Export")
    df = pd.DataFrame([{
        "question": question,
        "answer": result.get("answer", ""),
        "doc": docs[0] if docs else "",
        "page": pages[0] if pages else "",
        "status": status,
        "receipt": result.get("audit_receipt", ""),
    }])
    csv = df.to_csv(index=False).encode()
    st.download_button("Download CSV", csv, "tracerag_answer.csv", "text/csv")

# ── LENS 2: Journalist ────────────────────────────────────────────────────────

def lens_journalist(result: dict, question: str):
    st.subheader("📰 Journalist View")

    status = result.get("status", "")
    st.markdown(journalist_badge(status))
    st.markdown("---")

    if status == "refuse":
        st.error("This claim cannot be verified from the collection.")
        return

    answer = result.get("answer", "")
    docs   = _doc_list(result)
    pages  = _page_list(result)
    receipt = result.get("audit_receipt", "N/A")

    # Copyable citation
    if status == "conflict":
        answer_str = " vs ".join(answer) if isinstance(answer, list) else str(answer)
    else:
        answer_str = str(answer)

    doc_str  = docs[0]  if docs  else "Unknown document"
    page_str = str(pages[0]) if pages else "?"

    citation = (
        f'According to {doc_str} (page {page_str}): "{answer_str}". '
        f"[TraceRAG receipt: {receipt}]"
    )
    st.markdown("**📋 Citation (copy-ready)**")
    st.code(citation, language=None)

    if status == "conflict":
        st.warning(
            "⚠️ Values differ across editions. "
            "Quote both values and the document dates."
        )

    # Page image
    if docs and pages:
        bbox = result.get("bbox")
        if isinstance(bbox, str):
            try:
                bbox = json.loads(bbox)
            except Exception:
                bbox = None
        img = render_page_bytes(docs[0], pages[0], bbox)
        if img:
            with st.expander("Source page"):
                st.image(img, width="stretch")

    st.caption(f"Receipt ID: `{receipt}`")

# ── LENS 3: Student ───────────────────────────────────────────────────────────

GLOSSARY = {
    "CPI": "Consumer Price Index — measures average change in prices paid by consumers.",
    "FY": "Fiscal Year — April 1 to March 31 in India.",
    "CAG": "Comptroller and Auditor General of India.",
    "crore": "10 million (1 crore = 10,000,000).",
    "lakh": "100,000.",
    "BE": "Budget Estimate — planned government expenditure.",
    "RE": "Revised Estimate — updated budget figure.",
    "DTVsV": "Direct Tax Vivad se Vishwas — tax dispute resolution scheme.",
    "SSCA": "Special Subject of Compliance Audit.",
    "OCR": "Optical Character Recognition — reading text from scanned images.",
    "BM25": "A text-ranking algorithm used to find relevant documents.",
}

def lens_student(result: dict, question: str):
    st.subheader("🎓 Student View")

    status = result.get("status", "")
    answer = result.get("answer", "")

    if status == "refuse":
        st.info(
            "📚 The answer to this question **was not found** in the document collection. "
            "This could mean:\n"
            "- The topic is not covered in these reports.\n"
            "- The specific year or entity is different.\n"
            "Try rewording your question or checking other sources."
        )
        return

    # Plain-language explanation
    docs  = _doc_list(result)
    pages = _page_list(result)
    conf  = result.get("confidence", 0)

    if status == "conflict":
        answer_str = " and ".join(answer) if isinstance(answer, list) else str(answer)
        st.markdown(
            f"### 🤔 Two sources give different answers: **{answer_str}**\n\n"
            "This happens when a government report is updated and the number changes "
            "between editions. Always cite the specific report and year."
        )
    else:
        st.markdown(f"### ✅ The answer is: **{answer}**")
        ev = result.get("evidence", "")
        if ev:
            st.markdown("**How we found it:**")
            st.info(str(ev)[:400])

    if docs and pages:
        st.markdown(f"📄 Found in **{docs[0]}**, page **{pages[0]}**.")

    # OCR confidence warning
    if conf < 0.7 and conf > 0:
        st.warning(
            f"⚠️ **OCR confidence is low ({conf:.0%}).** "
            "This answer came from a scanned page — there may be small reading errors."
        )

    # Glossary
    text_to_scan = question + " " + str(answer) + " " + (result.get("evidence","") or "")
    found_terms = {k: v for k, v in GLOSSARY.items() if k in text_to_scan}
    if found_terms:
        with st.expander("📖 Glossary"):
            for term, defn in found_terms.items():
                st.markdown(f"**{term}** — {defn}")

    # Suggested follow-ups
    st.markdown("#### 💡 Suggested follow-up questions")
    suggestions = []
    if "inflation" in question.lower():
        suggestions = [
            "What was India's food inflation rate in FY24?",
            "How did core inflation change between FY23 and FY24?",
        ]
    elif "tomato" in question.lower() or "onion" in question.lower():
        suggestions = [
            "What was India's tomato production in 2022-23?",
            "How did onion production change between 2020-21 and 2021-22?",
        ]
    elif "kerala" in question.lower():
        suggestions = [
            "What is the total Kerala budget for 2026-27?",
            "What amount is set apart for education in Kerala's 2026-27 Budget?",
        ]
    elif "cag" in question.lower() or "audit" in question.lower():
        suggestions = [
            "How many cases were settled under the DTVsV scheme?",
            "What was the revenue collected under the DTVsV scheme?",
        ]
    else:
        suggestions = [
            "What was India's GDP growth rate in FY24?",
            "What is the fiscal deficit target for 2024-25?",
        ]
    for s in suggestions:
        st.markdown(f"- {s}")

# ── LENS 4: Fact-checker ──────────────────────────────────────────────────────

def lens_factchecker():
    st.subheader("🔍 Fact-Checker View")
    st.markdown(
        "Paste any claim and TraceRAG will check it against the document collection."
    )

    claim = st.text_area("Claim to check", height=80,
                          placeholder="e.g. India's retail inflation was 6% in FY24")
    check = st.button("Check claim ✔", width="stretch")

    if not check or not claim.strip():
        return

    with st.spinner("Checking…"):
        result = ask(claim.strip())

    status = result.get("status", "")
    answer = result.get("answer", "")
    docs   = _doc_list(result)
    pages  = _page_list(result)

    if status == "refuse":
        st.info("⚪ **Not in collection** — this claim cannot be verified or contradicted.")
        return

    # Does the claim's number match what we found?
    import re
    claim_nums = re.findall(r"\b\d+\.?\d*\b", claim)
    answer_str = str(answer)
    answer_nums = re.findall(r"\b\d+\.?\d*\b", answer_str)

    def nums_close(a, b, tol=0.02):
        try:
            return abs(float(a) - float(b)) / (abs(float(b)) + 1e-9) <= tol
        except Exception:
            return False

    supported = False
    if claim_nums and answer_nums:
        for cn in claim_nums:
            for an in answer_nums:
                if nums_close(cn, an):
                    supported = True
                    break

    if status == "conflict":
        st.warning(
            f"🟡 **CONFLICTING SOURCES**\n\n"
            f"The collection has different values: {answer_str}.\n"
            f"Cannot confirm or deny the claim definitively."
        )
    elif supported:
        st.success(
            f"✅ **SUPPORTED**\n\n"
            f"Found matching value **{answer_str}** in `{docs[0] if docs else ''}` "
            f"(page {pages[0] if pages else '?'})."
        )
    else:
        st.error(
            f"❌ **CONTRADICTED**\n\n"
            f"The collection reports **{answer_str}** (page {pages[0] if pages else '?'}), "
            f"not the value in your claim."
        )

    # Show source page
    if docs and pages:
        bbox = result.get("bbox")
        if isinstance(bbox, str):
            try:
                bbox = json.loads(bbox)
            except Exception:
                bbox = None
        img = render_page_bytes(docs[0], pages[0], bbox)
        if img:
            with st.expander("Source page"):
                st.image(img, width="stretch")

    st.caption(f"Receipt: {result.get('audit_receipt','N/A')}")

# ── LENS 5: Auditor ───────────────────────────────────────────────────────────

def lens_auditor():
    st.subheader("🔐 Auditor View")
    st.caption(
        "⚠️ The audit log is **tamper-evident, not tamper-proof**. "
        "An attacker with the HMAC key could re-sign the chain."
    )

    audit = get_audit()
    ok, msg = audit.verify_chain()

    # Chain integrity badge
    if ok:
        st.success(f"🔒 **Chain Intact** — {msg}")
    else:
        st.error(f"💥 **Chain BROKEN** — {msg}")

    col1, col2 = st.columns(2)

    # Decision mix
    with col1:
        st.markdown("#### Decision Mix")
        mix = audit.get_decision_mix()
        if any(mix.values()):
            df_mix = pd.DataFrame(
                [{"Status": k, "Count": v} for k, v in mix.items() if v > 0]
            )
            st.bar_chart(df_mix.set_index("Status"))
        else:
            st.info("No decisions logged yet.")

    # Refusal ledger
    with col2:
        st.markdown("#### Refusal Ledger")
        ledger = audit.get_refusal_ledger()
        if ledger:
            df_ledger = pd.DataFrame([{
                "ID": r.get("question_id",""),
                "Reason": r.get("reason",""),
                "Time": r.get("ts","")[:19],
            } for r in ledger])
            st.dataframe(df_ledger, width="stretch")
        else:
            st.info("No refusals logged yet.")

    # Export
    st.markdown("#### Export Audit Log")
    if st.button("Export JSONL"):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            n = audit.export_jsonl(tmp.name)
            with open(tmp.name, "rb") as f:
                data = f.read()
        st.download_button(
            f"Download audit ({n} records)", data,
            "audit_export.jsonl", "application/json"
        )

    # Tamper demo
    st.markdown("#### 🔧 Tamper Demo")
    st.markdown(
        "This creates a **copy** of the log, edits one record, "
        "and shows the chain breaking — the original log is never touched."
    )
    if st.button("Run tamper demo"):
        demo_dir = str(INDEX_DIR / "tamper_demo")
        with st.spinner("Running…"):
            demo_result = audit.tamper_demo(demo_dir)

        st.markdown("**Original log:**")
        if demo_result.get("original_chain_ok"):
            st.success("✅ Chain intact")
        else:
            st.error("💥 Chain broken")
        st.caption(demo_result.get("original_message",""))

        st.markdown("**Tampered copy:**")
        if demo_result.get("tampered_chain_ok"):
            st.success("✅ Chain intact (tamper not detected — unexpected)")
        else:
            st.error("💥 Chain broken — tamper detected!")
        st.caption(demo_result.get("tampered_message",""))
        st.info(demo_result.get("note",""))


# ── Enterprise Master UI Views ────────────────────────────────────────────────

def view_home(user, result, question, allowed, idx_dir, pdf_dir, is_gov):
    role_info = get_role_info(user["role"])
    
    # Hero Welcome Banner
    st.markdown(
        f"""
        <div class="dashboard-card" style="border-left: 4px solid #15803d; background: #ffffff;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <h2 style="color:#0f281e; margin:0 0 0.35rem 0; font-size:1.4rem;">
                        Welcome to TraceRAG Enterprise, {user['name']}
                    </h2>
                    <p style="color:#64748b; margin:0; font-size:0.875rem;">
                        Operational Workspace: <strong>{role_info['label']}</strong> · 
                        Mode: <strong>{'🔒 Government Offline (100% Local)' if is_gov else '🌐 Online Cloud'}</strong>
                    </p>
                </div>
                <div style="font-size:2.2rem;">{role_info['icon']}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Top KPI Metrics row
    doc_count = len(list_user_documents(user["username"], user["role"], is_government=is_gov))
    fact_count = 0
    refusal_count = 0
    audit_ok = True
    try:
        from tracerag.audit import AuditLog
        aud = AuditLog(str(idx_dir))
        audit_ok, _ = aud.verify_chain()
        refusal_count = len(aud.get_refusal_ledger())
    except Exception:
        pass

    try:
        with sqlite3.connect(str(idx_dir / "facts.db")) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM facts")
            fact_count = cur.fetchone()[0]
    except Exception:
        pass

    render_dashboard_metrics(doc_count, fact_count, audit_ok, refusal_count)
    st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)

    # Quick Action Cards (4 Cards)
    st.markdown("### ⚡ Quick Actions")
    qa1, qa2, qa3, qa4 = st.columns(4)
    with qa1:
        st.markdown(
            """
            <div class="dashboard-card" style="height:140px;">
                <div style="font-size:1.4rem; margin-bottom:0.25rem;">📤</div>
                <div class="card-title">Upload Document</div>
                <div class="card-desc">PDF, Scanned, CSV, Excel, Images, or Video.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Go to Uploads →", key="btn_qa_upload", width='stretch',
                     on_click=lambda: st.session_state.update({"enterprise_nav": "📁 My Documents"})):
            pass

    with qa2:
        st.markdown(
            """
            <div class="dashboard-card" style="height:140px;">
                <div style="font-size:1.4rem; margin-bottom:0.25rem;">❓</div>
                <div class="card-title">Ask a Question</div>
                <div class="card-desc">Ground every answer in original pixels.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Q&A →", key="btn_qa_ask", width="stretch",
                     on_click=lambda: st.session_state.update({"enterprise_nav": "❓ Ask a Question"})):
            pass

    with qa3:
        st.markdown(
            """
            <div class="dashboard-card" style="height:140px;">
                <div style="font-size:1.4rem; margin-bottom:0.25rem;">📑</div>
                <div class="card-title">Reports & Comparison</div>
                <div class="card-desc">Cross-document YoY deltas & conflict checks.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("View Reports →", key="btn_qa_reports", width="stretch",
                     on_click=lambda: st.session_state.update({"enterprise_nav": "📊 Reports & Comparisons"})):
            pass

    with qa4:
        st.markdown(
            """
            <div class="dashboard-card" style="height:140px;">
                <div style="font-size:1.4rem; margin-bottom:0.25rem;">🔍</div>
                <div class="card-title">Evidence Explorer</div>
                <div class="card-desc">Inspect bounding boxes and source pages.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Explore Evidence →", key="btn_qa_explore", width="stretch",
                     on_click=lambda: st.session_state.update({"enterprise_nav": "🔍 Evidence Explorer"})):
            pass

    # Recent Documents Summary Table
    st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)
    st.markdown("### 📄 Recent Documents")
    user_docs = list_user_documents(user["username"], user["role"], is_government=is_gov)
    if user_docs:
        df_docs = pd.DataFrame([{
            "Filename": d["filename"],
            "Format": d["file_type"].upper(),
            "Size (KB)": round(d["file_size"] / 1024, 1),
            "Status": f"✅ {d['status'].capitalize()}",
            "Uploaded": d["upload_time"][:16].replace("T", " "),
        } for d in user_docs[:5]])
        st.dataframe(df_docs, width="stretch", hide_index=True)
    else:
        st.info("No user-uploaded documents yet. Upload your first document via 'My Documents'.")

    # Render Role Analysis Lenses & Tabs
    st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)
    st.markdown(f"### {role_info['icon']} Role Analysis Workspace: {role_info['label']}")
    if is_gov:
        _government_dashboard(result, question, allowed, idx_dir)
    else:
        _online_dashboard(result, question, allowed)


def view_ask_question(user, result, question, allowed, idx_dir, pdf_dir, is_gov):
    st.markdown("### ❓ Natural Language Query & Explainability Engine")
    st.caption("Ask questions across all indexed reports, tables, and charts. Every answer is grounded with bounding box verification.")
    
    col_q, col_btn = st.columns([5, 1])
    with col_q:
        q_input = st.text_input("Enter your question", value=question, placeholder="e.g. What was India's retail inflation in FY24?", key="main_q_input")
    with col_btn:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        search_click = st.button("Search & Verify", type="primary", width="stretch")

    if search_click and q_input:
        with st.spinner("Searching and verifying against original sources…"):
            from tracerag.engine import Engine
            _eng = Engine(str(idx_dir), str(pdf_dir))
            qid  = f"ui_{int(time.time()*1000)}"
            st.session_state.result   = _eng.answer(qid, q_input, strict=False)
            st.session_state.question = q_input
            result = st.session_state.result
            question = q_input

    if result:
        st.divider()
        status = result.get("status", "answer")
        ans_val = result.get("answer", "")
        if isinstance(ans_val, list):
            ans_display = " | ".join(str(a) for a in ans_val)
        else:
            ans_display = str(ans_val)

        badge_class = "badge-verified" if status == "answer" else ("badge-conflict" if status == "conflict" else "badge-refuse")
        badge_text = "VERIFIED ANSWER" if status == "answer" else ("CONFLICTING SOURCES" if status == "conflict" else "REFUSED — NO EVIDENCE")
        
        st.markdown(
            f"""
            <div class="dashboard-card" style="border-left: 4px solid {'#10b981' if status=='answer' else ('#f59e0b' if status=='conflict' else '#ef4444')};">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                    <span class="card-title" style="font-size:1.1rem;">Answer Result</span>
                    <span class="{badge_class}">{badge_text}</span>
                </div>
                <div style="font-size:1.35rem; font-weight:700; color:#0f281e; margin-bottom:0.5rem;">
                    {ans_display if ans_display else '(Refused — no verifiable claim supported by documents)'}
                </div>
                <div style="font-size:0.825rem; color:#6b7280;">
                    Document: <code>{result.get('doc')}</code> · Page: <code>{result.get('page')}</code> · Confidence: <code>{result.get('confidence', 1.0)}</code> · Receipt: <code>{result.get('audit_receipt', 'N/A')}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Highlighted Evidence Region View
        doc_name = result.get("doc")
        page_num = result.get("page")
        bbox = result.get("bbox")

        if isinstance(doc_name, list) and doc_name:
            doc_name = doc_name[0]
        if isinstance(page_num, list) and page_num:
            page_num = page_num[0]

        if doc_name and page_num:
            st.markdown("#### 🖼️ Source Grounding & Bounding Box Highlight")
            img_bytes = render_page_bytes(str(doc_name), int(page_num), bbox)
            if img_bytes:
                st.image(img_bytes, caption=f"Original Source: {doc_name} (Page {page_num})", width="stretch")

    st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)
    if is_gov:
        _government_dashboard(result, question, allowed, idx_dir)
    else:
        _online_dashboard(result, question, allowed)


def view_my_documents(user, is_gov, idx_dir, pdf_dir):
    st.markdown("### 📁 Universal Document Management & Library")
    st.caption("Upload and manage private documents across PDF, Scanned PDF, Images, CSV, Excel, and Video. Only you have access to your uploaded files.")

    # Multi-file Uploader
    uploaded_files = st.file_uploader(
        "Upload files (PDF, PNG, JPG, CSV, XLSX, MP4)",
        type=["pdf", "png", "jpg", "jpeg", "csv", "xlsx", "mp4"],
        accept_multiple_files=True,
        key="universal_doc_uploader",
    )

    if uploaded_files:
        if st.button("🚀 Process & Ingest Files", type="primary", width="stretch"):
            prog = st.progress(0.0, text="Validating files…")
            db = idx_dir / "facts.db"
            conn = sqlite3.connect(str(db))
            for i, uf in enumerate(uploaded_files):
                pct = (i + 1) / len(uploaded_files)
                prog.progress(pct, text=f"Processing {uf.name}…")
                data = uf.read()
                ext = Path(uf.name).suffix.lower()
                ftype = (
                    "pdf"
                    if ext == ".pdf"
                    else ("image" if ext in [".png", ".jpg", ".jpeg"] else ("csv" if ext == ".csv" else ("excel" if ext == ".xlsx" else "video")))
                )

                # Register document (creates storage & DB entry)
                rec = register_document(
                    filename=uf.name,
                    file_type=ftype,
                    file_bytes=data,
                    owner_username=user["username"],
                    owner_role=user["role"],
                    is_government=is_gov,
                )

                fact_count = 0
                try:
                    if ftype == "csv":
                        fact_count = ingest_csv_facts(rec["file_path"], uf.name, conn)
                    elif ftype == "image":
                        fact_count = ingest_image_facts(rec["file_path"], uf.name, conn)
                    elif ftype == "video":
                        fact_count = ingest_video_facts(rec["file_path"], uf.name, conn, str(rec["index_path"]))
                    elif ftype == "pdf":
                        from study.upload import validate_pdf
                        validate_pdf(data, uf.name)
                        dest_pdf = pdf_dir / uf.name
                        dest_pdf.write_bytes(data)
                        from tracerag.ingest import ingest_single_pdf
                        fact_count = ingest_single_pdf(str(dest_pdf), str(idx_dir))
                    update_document_status(rec["doc_id"], "ready", is_gov, fact_count=fact_count)
                except Exception as e:
                    update_document_status(rec["doc_id"], "error", is_gov, error_message=str(e))
                    st.error(f"Error processing {uf.name}: {e}")
            conn.close()
            prog.progress(1.0, text="Completed!")
            st.success("✅ Files processed and indexed successfully!")
            time.sleep(0.8)
            st.rerun()

    # Document Library Search and List
    st.divider()
    st.markdown("#### 📚 Your Document Library")
    search_q = st.text_input("🔍 Search document library", placeholder="Search by filename…")
    docs = list_user_documents(user["username"], user["role"], is_government=is_gov, search_query=search_q)
    if docs:
        for d in docs:
            with st.container():
                st.markdown(
                    f"""
                    <div class=\"dashboard-card\" style=\"margin-bottom:0.75rem;\">
                        <div style=\"display:flex; justify-content:space-between; align-items:center;\">
                            <div>
                                <strong style=\"font-size:1rem; color:#0f281e;\">{d['filename']}</strong>
                                <span class=\"top-nav-badge badge-role\" style=\"margin-left:0.5rem;\">{d['file_type'].upper()}</span>
                                <span style=\"font-size:0.8rem; color:#6b7280; margin-left:0.5rem;\">{round(d['file_size']/1024, 1)} KB · {d['upload_time'][:16].replace('T', ' ')}</span>
                            </div>
                            <span class=\"badge-online\">{'✅ ' + d['status'].capitalize()}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                c_del, c_ask, c_space = st.columns([1, 2, 4])
                with c_del:
                    if st.button("🗑 Delete", key=f"del_{d['doc_id']}", width="stretch"):
                        delete_document(d["doc_id"], user["username"], user["role"], is_gov)
                        st.success(f"Deleted {d['filename']}.")
                        st.rerun()
                with c_ask:
                    def _go_ask_doc(fname=d['filename']):
                        st.session_state["enterprise_nav"] = "❓ Ask a Question"
                        st.session_state["question"] = f"From {fname}, what are the key findings?"
                    st.button("❓ Ask about this doc", key=f"ask_{d['doc_id']}",
                              width="stretch", on_click=_go_ask_doc)

                # Student role AI summarization & quiz generation (ONLINE ONLY, NOT in gov offline mode)
                if user.get("role") == "student":
                    if is_gov:
                        st.info("🔒 Offline Government Mode: External AI summary/quiz generation is disabled.")
                    else:
                        with st.expander(f"🎓 Student Tools for {d['filename']}"):
                            api_key = os.getenv("OPENAI_API_KEY")
                            if not api_key:
                                st.warning("⚠️ OpenAI API key required for AI summarization & quiz generation. Set OPENAI_API_KEY environment variable to enable.")
                            else:
                                col_sum, col_quiz = st.columns(2)
                                with col_sum:
                                    if st.button(f"📝 Summarize {d['filename']}", key=f"sum_{d['doc_id']}", width="stretch"):
                                        with st.spinner("Generating summary via OpenAI…"):
                                            s_text = summarize_document(d["file_path"])
                                            st.session_state[f"summary_{d['doc_id']}"] = s_text
                                with col_quiz:
                                    if st.button(f"🧠 Quiz & Flashcards for {d['filename']}", key=f"quiz_{d['doc_id']}", width="stretch"):
                                        with st.spinner("Generating quiz and flashcards…"):
                                            s_text = st.session_state.get(f"summary_{d['doc_id']}")
                                            if not s_text or s_text.startswith("⚠️"):
                                                s_text = summarize_document(d["file_path"])
                                                st.session_state[f"summary_{d['doc_id']}"] = s_text
                                            materials = generate_student_materials(s_text, api_key)
                                            st.session_state[f"mat_{d['doc_id']}"] = materials

                                if f"summary_{d['doc_id']}" in st.session_state:
                                    st.markdown("##### 📄 Summary")
                                    st.write(st.session_state[f"summary_{d['doc_id']}"])

                                if f"mat_{d['doc_id']}" in st.session_state:
                                    mat = st.session_state[f"mat_{d['doc_id']}"]
                                    if mat.get("quiz"):
                                        st.markdown("##### ❓ Practice Quiz Questions")
                                        for q in mat["quiz"]:
                                            st.markdown(f"- {q}")
                                    if mat.get("flashcards"):
                                        st.markdown("##### 🗂️ Flashcards (Term – Definition)")
                                        for fc in mat["flashcards"]:
                                            st.markdown(f"- {fc}")
    else:
        st.info("No documents found matching your filter.")


def view_media_library(user, is_gov, idx_dir, pdf_dir):
    st.markdown("### 🎬 Multimodal Media Library")
    st.caption("Browse extracted tables, charts, scanned OCR blocks, and video keyframes with bounding box annotations.")

    db = idx_dir / "facts.db"
    if not db.exists():
        st.info("No database available.")
        return

    with sqlite3.connect(str(db)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT kind FROM facts WHERE kind IS NOT NULL")
        kinds = [r[0] for r in cur.fetchall()]

    filter_kind = st.selectbox("Filter by Evidence Type", ["All"] + kinds)
    
    with sqlite3.connect(str(db)) as conn:
        cur = conn.cursor()
        if filter_kind == "All":
            cur.execute("SELECT doc, page, kind, metric, value, unit, period, raw_text, bbox FROM facts WHERE value_num IS NOT NULL LIMIT 40")
        else:
            cur.execute("SELECT doc, page, kind, metric, value, unit, period, raw_text, bbox FROM facts WHERE kind=? AND value_num IS NOT NULL LIMIT 40", (filter_kind,))
        rows = cur.fetchall()

    if rows:
        st.markdown(f"Displaying top **{len(rows)}** extracted multimodal evidence items:")
        for r in rows:
            doc, page, kind, metric, value, unit, period, raw_text, bbox = r
            with st.container():
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <strong>{metric or doc}</strong>
                            <span class="top-nav-badge badge-role">{kind.upper()}</span>
                        </div>
                        <div style="font-size:1.15rem; font-weight:700; color:#15803d; margin:0.35rem 0;">
                            {value} {unit or ''}
                        </div>
                        <div style="font-size:0.8rem; color:#4b5563;">
                            Period: <strong>{period or 'N/A'}</strong> · Document: <code>{doc}</code> · Page: <code>{page}</code>
                        </div>
                        <div style="font-size:0.75rem; color:#6b7280; margin-top:0.35rem;">
                            Evidence Context: <em>{raw_text[:180] if raw_text else ''}...</em>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    else:
        st.info("No media items found for this selection.")


def view_evidence_explorer(user, is_gov, idx_dir, pdf_dir):
    st.markdown("### 🔍 Evidence Explorer")
    st.caption("Inspect original source pages and zoom in on exact bounding box coordinate regions.")

    pdf_files = sorted([p.name for p in pdf_dir.glob("*.pdf")])
    if not pdf_files:
        st.info("No PDF files available in document storage.")
        return

    col_doc, col_pg = st.columns([3, 1])
    with col_doc:
        sel_doc = st.selectbox("Select Document", pdf_files)
    with col_pg:
        page_num = st.number_input("Page Number", min_value=1, max_value=300, value=1)

    img_bytes = render_page_bytes(sel_doc, int(page_num))
    if img_bytes:
        st.image(img_bytes, caption=f"{sel_doc} – Page {page_num}", width="stretch")
    else:
        st.warning(f"Could not render page {page_num} for {sel_doc}.")

    db = idx_dir / "facts.db"
    if db.exists():
        with sqlite3.connect(str(db)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT metric, value, unit, period, kind, bbox FROM facts WHERE doc=? AND page=?", (sel_doc, page_num))
            facts_page = cur.fetchall()
            if facts_page:
                st.markdown("#### Facts Extracted from this Page")
                df_page = pd.DataFrame(facts_page, columns=["Metric", "Value", "Unit", "Period", "Type", "Bounding Box"])
                st.dataframe(df_page, width="stretch", hide_index=True)


def view_reports_and_comparisons(user, is_gov, idx_dir):
    st.markdown("### 📊 Reports & Cross-Document Comparisons")
    st.caption("Compare metrics across multiple documents to identify growth trends, revised figures, and discrepancies.")

    tab_compare, tab_trends = st.tabs(["📑 Document Comparison", "📈 Metric Trend Analysis"])

    db = idx_dir / "facts.db"
    if not db.exists():
        st.info("No facts database found.")
        return

    with sqlite3.connect(str(db)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT doc FROM facts WHERE doc IS NOT NULL")
        docs = [r[0] for r in cur.fetchall()]

    with tab_compare:
        if len(docs) >= 2:
            c1, c2 = st.columns(2)
            with c1:
                doc1 = st.selectbox("First Document (Baseline)", docs, index=0)
            with c2:
                doc2 = st.selectbox("Second Document (Comparison)", docs, index=min(1, len(docs)-1))
            
            filter_kw = st.text_input("Optional Metric Keyword Filter", placeholder="e.g. inflation, production, tax")
            
            if st.button("Run Cross-Document Comparison", type="primary"):
                with sqlite3.connect(str(db)) as conn:
                    res = compare_documents(doc1, doc2, conn, metric_filter=filter_kw if filter_kw else None)
                
                if res["conflicts"]:
                    st.warning(f"⚠️ **{len(res['conflicts'])} Discrepancies / Conflicts Detected** between {doc1} and {doc2}")
                    df_conf = pd.DataFrame([{
                        "Metric": c["metric"],
                        "Period": c["period"],
                        f"{doc1} (p.{c['page1']})": c["value1"],
                        f"{doc2} (p.{c['page2']})": c["value2"],
                        "Delta": c["delta"],
                        "Discrepancy %": f"{c['pct_change']}%",
                    } for c in res["conflicts"]])
                    st.dataframe(df_conf, width="stretch", hide_index=True)
                else:
                    st.success("✅ No conflicting figures found for matching periods.")

                if res["comparisons"]:
                    st.markdown("#### Full Comparison Table")
                    df_comp = pd.DataFrame([{
                        "Metric": c["metric"],
                        "Period": c["period"],
                        "Val 1": c["value1"],
                        "Val 2": c["value2"],
                        "Delta": c["delta"],
                        "Change %": f"{c['pct_change']}%",
                        "Status": "⚠️ Conflict" if c["status"] == "conflict" else "✅ Match",
                    } for c in res["comparisons"]])
                    st.dataframe(df_comp, width="stretch", hide_index=True)
                else:
                    st.info("No directly overlapping metrics found between these two documents.")
        else:
            st.info("At least two documents must be indexed to run cross-document comparison.")

    with tab_trends:
        st.markdown("#### Trace Metric Across All Periods")
        kw = st.text_input("Metric Name to Trace", value="inflation", placeholder="e.g. inflation, GDP, tomato, revenue")
        if kw:
            with sqlite3.connect(str(db)) as conn:
                trends = analyze_metric_trend(kw, conn)
            if trends:
                df_trend = pd.DataFrame([{
                    "Document": t["doc"],
                    "Page": t["page"],
                    "Metric": t["metric"],
                    "Period": t["period"],
                    "Value": f"{t['value']} {t['unit'] or ''}",
                    "YoY Delta": t["delta"] if t["delta"] is not None else "—",
                    "Growth %": f"{t['pct_change']}%" if t["pct_change"] is not None else "—",
                } for t in trends])
                st.dataframe(df_trend, width="stretch", hide_index=True)
            else:
                st.info(f"No trends found for '{kw}'.")


def view_audit_trail(user, is_gov, idx_dir):
    st.markdown("### 🛡️ Audit Trail & Integrity Ledger")
    st.caption("Cryptographic HMAC-SHA256 chained log ensuring complete tamper-evidence across all queries, uploads, and decisions.")

    from tracerag.audit import AuditLog
    audit = AuditLog(str(idx_dir))
    ok, msg = audit.verify_chain()

    if ok:
        st.success(f"🔒 **HMAC-SHA256 Hash Chain: INTACT** — {msg}")
    else:
        st.error(f"💥 **HMAC-SHA256 Hash Chain: BROKEN** — {msg}")

    c_mix, c_ref = st.columns(2)
    with c_mix:
        st.markdown("#### System Decision Mix")
        mix = audit.get_decision_mix()
        if any(mix.values()):
            df_mix = pd.DataFrame([{"Status": k.upper(), "Count": v} for k, v in mix.items() if v > 0])
            st.bar_chart(df_mix.set_index("Status"))
        else:
            st.info("No decisions recorded yet.")

    with c_ref:
        st.markdown("#### Refusal Ledger")
        ledger = audit.get_refusal_ledger()
        if ledger:
            df_ledger = pd.DataFrame([{
                "Question ID": r.get("question_id", ""),
                "Reason Code": r.get("reason", ""),
                "Timestamp": r.get("ts", "")[:19],
            } for r in ledger])
            st.dataframe(df_ledger, width="stretch", hide_index=True)
        else:
            st.info("No refusals logged.")

    st.divider()
    c_exp, c_tamper = st.columns(2)
    with c_exp:
        st.markdown("#### Export Audit Log")
        if st.button("Export to JSONL", width="stretch"):
            with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
                n = audit.export_jsonl(tmp.name)
                with open(tmp.name, "rb") as f:
                    data = f.read()
            st.download_button(
                f"📥 Download ({n} records)",
                data,
                "audit_export.jsonl",
                "application/json",
                width="stretch",
            )

    with c_tamper:
        st.markdown("#### 🔧 Tamper Detection Test Suite")
        if st.button("Run Tamper Test", width="stretch"):
            demo_dir = str(idx_dir / "tamper_demo")
            with st.spinner("Testing tamper resistance…"):
                res = audit.tamper_demo(demo_dir)
            if res.get("tampered_chain_ok") is False:
                st.success("✅ **Tamper Detected!** Modified row was immediately flagged by hash chain mismatch.")
            else:
                st.error("Failed to detect tampering.")


def view_settings(user, is_gov, idx_dir):
    st.markdown("### ⚙️ System Settings & Environment Configuration")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Environment Settings")
        st.text_input("Active Environment", value="Government Offline (Isolated)" if is_gov else "Online Cloud", disabled=True)
        st.text_input("Database Path", value=str(idx_dir / "facts.db"), disabled=True)
        st.text_input("Document Store", value=str(idx_dir / "docstore.db"), disabled=True)
        st.text_input("Audit Log Path", value=str(idx_dir / "audit.jsonl"), disabled=True)
    with col2:
        st.markdown("#### AI & Retrieval Configuration")
        st.text_input("AI Provider", value="Local Extractive (Offline Safe)" if is_gov else "Cloud / Hybrid", disabled=True)
        st.text_input("Hybrid Retrieval Fusion", value="BM25 + IDF Coverage + RRF (k=60)", disabled=True)
        st.text_input("Verification Tolerance", value="1.5% Relative Numeric Tolerance", disabled=True)
        st.text_input("Signed-in User", value=f"{user['name']} ({user['role']})", disabled=True)


def view_help_and_support(user, is_gov):
    st.markdown("### ❓ Help, Documentation & Role Guide")
    st.markdown(
        """
        #### 🏛️ About TraceRAG
        TraceRAG is an enterprise Multimodal Evidence-Intelligence Platform.
        Key capabilities:
        - **Claim-to-Pixel Grounding**: Every numeric value and statement is verified against original document page coordinates.
        - **Intelligent Refusal**: If a figure or entity is absent from the repository, TraceRAG refuses instead of hallucinating.
        - **Tamper-Evident Auditing**: Every query and decision is written to an HMAC-SHA256 chained audit ledger.
        
        #### 👥 Role Privileges Matrix
        | Role | Environment | Key Capabilities |
        |---|---|---|
        | **Government** | 🔒 Offline | 100% local processing, zero external network calls, confidential report analysis |
        | **Policy Analyst** | 🌐 Online | Multi-document trend comparisons, year-over-year statistics, policy briefs |
        | **Journalist** | 🌐 Online | Fact verification badge, quote-ready evidence, source citation export |
        | **Student** | 🌐 Online | Study notes, verified flashcards, interactive quizzes, practice questions |
        | **Fact-Checker** | 🌐 Online | Claim submission, debunking, contradiction detection, missing context finder |
        | **Auditor / Admin** | 🌐 Online | HMAC chain validation, refusal ledger, tamper test suite, JSONL audit export |
        """
    )

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="TraceRAG",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialise navigation key BEFORE any widget reads it (Streamlit requirement)
    if "enterprise_nav" not in st.session_state:
        st.session_state["enterprise_nav"] = "🏠 Home"

    # Login gate — single page for all roles
    if not st.session_state.get("user"):
        _show_login()
        return

    user   = st.session_state["user"]
    role   = user["role"].lower().strip()
    is_gov = (role == "government")

    # Paths are scoped to the user's environment
    _idx_dir = ROOT / "data" / "gov_index" if is_gov else ROOT / "data" / "index"
    _pdf_dir = ROOT / "data" / "gov_pdfs"  if is_gov else ROOT / "data" / "raw" / "pdfs"

    apply_enterprise_theme()
    render_top_navbar(user, title="TraceRAG Enterprise Platform")

    # Route strictly to independent role dashboard
    if role == "government":
        render_government_interface(user, _idx_dir, _pdf_dir)
    elif role == "analyst":
        render_analyst_interface(user, _idx_dir, _pdf_dir)
    elif role == "journalist":
        render_journalist_interface(user, _idx_dir, _pdf_dir)
    elif role == "student":
        render_student_dashboard(user, _idx_dir, _pdf_dir)
    elif role == "factchecker":
        render_factchecker_interface(user, _idx_dir, _pdf_dir)
    elif role == "auditor":
        render_auditor_dashboard(user, _idx_dir, _pdf_dir)
    else:
        st.error(f"Unrecognized role: {role}")


# ── Login screen (single page, login + create account) ───────────────────────

def _show_login():
    apply_enterprise_theme()
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown(
            """
            <div style="text-align:center; padding: 1.5rem 0 0.5rem 0;">
                <div style="font-size:2.5rem; line-height:1;">🌿</div>
                <h1 style="color:#0f281e; font-weight:800; margin-bottom:0.25rem;">TraceRAG</h1>
                <p style="color:#64748b; font-size:0.95rem; margin-top:0;">Enterprise Multimodal Evidence-Intelligence Platform</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        tab_login, tab_register = st.tabs(["🔐 Sign In", "📝 Create Account"])

        # ── Sign In tab ───────────────────────────────────────────────────────
        with tab_login:
            with st.form("login_form"):
                username  = st.text_input("Username", placeholder="your-username")
                password  = st.text_input("Password", type="password",
                                           placeholder="your-password")
                submitted = st.form_submit_button("Login →",
                                                   width="stretch",
                                                   type="primary")
            if submitted:
                if not username or not password:
                    st.warning("Enter both username and password.")
                else:
                    try:
                        user = authenticate(username, password)
                        st.session_state["user"] = user
                        env_label = "🔒 Government Offline" if user["offline"] else "🌐 Online"
                        ri = get_role_info(user["role"])
                        st.success(
                            f"{ri['icon']} Welcome **{user['name']}** — "
                            f"entering **{env_label}** environment."
                        )
                        time.sleep(0.8)
                        st.rerun()
                    except AuthError as e:
                        st.error(f"❌ {e}")

        # ── Create Account tab ────────────────────────────────────────────────
        with tab_register:
            st.info("🔒 Government and Auditor accounts require administrator provisioning.")
            with st.form("register_form"):
                reg_name  = st.text_input("Full Name", placeholder="Your Name")
                reg_user  = st.text_input("Username",  placeholder="choose-a-username")
                reg_pass  = st.text_input("Password",  type="password",
                                           placeholder="at least 6 characters")
                reg_pass2 = st.text_input("Confirm Password", type="password")
                reg_role  = st.selectbox("Select Role", [
                    "student", "analyst", "journalist", "factchecker"
                ], format_func=lambda r: {
                    "student":     "🎓 Student",
                    "analyst":     "📊 Policy Analyst",
                    "journalist":  "📰 Journalist",
                    "factchecker": "🔍 Fact-Checker",
                }.get(r, r))
                reg_btn = st.form_submit_button("Create Account →",
                                                 width="stretch",
                                                 type="primary")
            if reg_btn:
                if reg_pass != reg_pass2:
                    st.error("Passwords do not match.")
                else:
                    try:
                        from auth import create_account
                        user = create_account(reg_user, reg_pass, reg_name, reg_role)
                        st.session_state["user"] = user
                        st.success(
                            f"✅ Account created! Welcome **{user['name']}**. "
                            "Logging you in…"
                        )
                        time.sleep(0.8)
                        st.rerun()
                    except AuthError as e:
                        st.error(f"❌ {e}")


# ── Government offline dashboard ──────────────────────────────────────────────

def _government_dashboard(result, question, allowed, idx_dir):
    """Offline dashboard for government role — local pipelines only."""
    # Status bar
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Environment", "🔒 Offline")
    c2.metric("AI",          "Local only")
    c3.metric("Database",    "Local SQLite")
    try:
        from tracerag.audit import AuditLog
        ok, _ = AuditLog(str(idx_dir)).verify_chain()
        c4.metric("Audit Chain", "✅ Intact" if ok else "❌ Broken")
    except Exception:
        c4.metric("Audit Chain", "⚠️ N/A")
    st.divider()

    all_tab_defs = {
        "📊 Analyst":      lambda: lens_analyst(result, question) if result else st.info("Ask a question via the sidebar."),
        "🔍 Fact-checker": lens_factchecker,
        "🔐 Auditor":      lens_auditor,
        "📚 My PDFs":      study_tab_my_pdfs,
    }
    tab_names = [t for t in allowed if t in all_tab_defs]
    tabs = st.tabs(tab_names)
    for tab, name in zip(tabs, tab_names):
        with tab:
            all_tab_defs[name]()


# ── Online dashboard ──────────────────────────────────────────────────────────

def _online_dashboard(result, question, allowed):
    all_tab_defs = {
        "📊 Analyst":      lambda: lens_analyst(result, question) if result else st.info("Ask a question."),
        "📰 Journalist":   lambda: lens_journalist(result, question) if result else st.info("Ask a question."),
        "🎓 Student":      lambda: lens_student(result, question) if result else st.info("Ask a question."),
        "🔍 Fact-checker": lens_factchecker,
        "🔐 Auditor":      lens_auditor,
        "📤 Upload":       study_tab_upload,
        "📝 Summary":      study_tab_summary,
        "🃏 Flashcards":   study_tab_flashcards,
        "🧠 Quiz":         study_tab_quiz,
        "▶️ Videos":       study_tab_videos,
        "❓ Ask":          study_tab_ask,
        "📈 Progress":     study_tab_progress,
        "📚 My PDFs":      study_tab_my_pdfs,
    }
    tab_names = [t for t in allowed if t in all_tab_defs]
    tabs = st.tabs(tab_names)
    for tab, name in zip(tabs, tab_names):
        with tab:
            all_tab_defs[name]()


# ═══════════════════════════════════════════════════════════════════════════════
# STUDENT STUDY MODE — tabs 5-11
# ═══════════════════════════════════════════════════════════════════════════════

def _study_session_state():
    """Initialise all study-mode session state keys."""
    defaults = {
        "study_session_id":  None,
        "study_dirs":        None,
        "study_manifest":    {},
        "study_topics":      [],
        "study_summaries":   {},
        "study_cards":       [],
        "study_leitner":     None,
        "study_quiz_q":      None,
        "study_quiz_ans":    None,
        "study_quiz_score":  {"correct": 0, "total": 0},
        "study_flip":        {},    # card_id → bool (flipped?)
        "study_pdf_names":   [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _render_source(doc: str, page: int, bbox, session_dirs: dict):
    """Render a PDF page with highlight inside an expander."""
    if not doc or not page:
        return
    pdf_path = session_dirs["pdfs"] / doc
    if not pdf_path.exists():
        # Try shared collection
        pdf_path = PDF_DIR / doc
    if not pdf_path.exists():
        return
    img = render_page_bytes(str(pdf_path), page, bbox, dpi=120)
    if img:
        with st.expander(f"📄 Source: {doc} p.{page}"):
            st.image(img, width="stretch")


# ── Tab: Upload ───────────────────────────────────────────────────────────────

def study_tab_upload():
    _study_session_state()
    from study.upload import (
        new_session_id, session_dirs, validate_pdf, save_upload,
        ingest_session_pdf, sha256_of, log_upload, delete_session,
        cleanup_expired_sessions, get_ocr_stats, UploadError,
        MAX_UPLOAD_MB, MAX_PAGES,
    )

    st.subheader("📤 Upload Your PDF")
    st.caption(
        f"Max {MAX_UPLOAD_MB} MB · Max {MAX_PAGES} pages · "
        "No password-protected or JavaScript-containing files."
    )

    # Auto-cleanup expired sessions
    cleanup_expired_sessions()

    uploaded = st.file_uploader(
        "Choose one or more PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        process_btn = st.button("Process PDFs ▶", type="primary",
                                width="stretch",
                                disabled=not uploaded)
    with col2:
        delete_btn = st.button("🗑 Delete my files",
                               width="stretch",
                               disabled=st.session_state.study_session_id is None)

    if delete_btn and st.session_state.study_session_id:
        delete_session(st.session_state.study_session_id)
        for k in list(st.session_state.keys()):
            if k.startswith("study_"):
                del st.session_state[k]
        _study_session_state()
        st.success("Files deleted.")
        st.rerun()

    if not process_btn or not uploaded:
        if st.session_state.study_session_id:
            st.info(f"Session active: `{st.session_state.study_session_id[:8]}…`  "
                    f"({len(st.session_state.study_pdf_names)} file(s) loaded)")
        return

    # New session
    sid  = new_session_id()
    dirs = session_dirs(sid)

    progress = st.progress(0.0, text="Validating…")
    errors   = []
    saved    = []

    for i, uf in enumerate(uploaded):
        pct = (i / len(uploaded)) * 0.3
        progress.progress(pct, text=f"Validating {uf.name}…")
        data = uf.read()
        try:
            validate_pdf(data, uf.name)
            save_upload(sid, uf.name, data)
            log_upload(sid, uf.name, sha256_of(data), str(dirs["index"]))
            saved.append(uf.name)
        except UploadError as e:
            errors.append(f"**{uf.name}**: {e}")

    if errors:
        for err in errors:
            st.error(err)
        if not saved:
            return

    # ── Step 1: Index the PDF ────────────────────────────────────────────────
    progress.progress(0.35, text="Indexing PDF (extracting text, tables, charts)…")
    try:
        import logging
        logging.getLogger("tracerag.ingest").setLevel(logging.WARNING)
        manifest = ingest_session_pdf(sid, saved[0])
        progress.progress(0.55, text=f"Indexed {saved[0]}…")
    except Exception as e:
        st.error(f"❌ Indexing failed: {e}")
        import traceback
        st.code(traceback.format_exc(), language="python")
        return

    # ── Step 2: Extract topics ────────────────────────────────────────────────
    progress.progress(0.60, text="Extracting topics…")
    from study.topics import extract_topics
    from study.summarise import summarise_topic
    from study.flashcards import generate_cards
    from study.leitner import LeitnerDeck

    topics    = []
    summaries = {}
    all_cards = []

    for fname in saved:
        pdf_path  = str(dirs["pdfs"] / fname)
        reg_jsonl = str(dirs["index"] / "regions.jsonl")
        try:
            t = extract_topics(pdf_path, reg_jsonl)
            if not t:
                st.warning(f"⚠️ No topics found in {fname}. Using full document as one topic.")
                t = [{
                    "id": "t00", "title": fname.replace(".pdf",""),
                    "page_start": 1, "page_end": 999,
                    "source": "fallback", "region_ids": [], "page_texts": {},
                }]
                # Attach all regions to the fallback topic
                from study.topics import _attach_regions
                t = _attach_regions(t, reg_jsonl)
            topics.extend(t)
        except Exception as e:
            st.error(f"❌ Topic extraction failed for {fname}: {e}")
            continue

    if not topics:
        st.error("❌ Could not extract any topics. Please try a different PDF.")
        return

    progress.progress(0.70, text=f"Building summaries for {len(topics)} topics…")

    # ── Step 3: Summarise + generate cards ───────────────────────────────────
    for idx, topic in enumerate(topics):
        pct = 0.70 + (idx / max(len(topics), 1)) * 0.25
        progress.progress(pct, text=f"Summarising: {topic['title'][:40]}…")
        try:
            s = summarise_topic(topic, str(dirs["index"]), saved[0])
            summaries[topic["id"]] = s
        except Exception as e:
            st.warning(f"⚠️ Summary failed for '{topic['title']}': {e}")
            summaries[topic["id"]] = {"title": topic["title"], "bullets": [], "key_numbers": []}

        try:
            cards = generate_cards(
                topic, summaries[topic["id"]],
                str(dirs["index"]), saved[0],
                str(dirs["pdfs"] / saved[0])
            )
            all_cards.extend(cards)
        except Exception as e:
            st.warning(f"⚠️ Card generation failed for '{topic['title']}': {e}")

    # ── Step 4: Store results ─────────────────────────────────────────────────
    deck = LeitnerDeck(all_cards) if all_cards else LeitnerDeck([])
    st.session_state.study_session_id = sid
    st.session_state.study_dirs       = dirs
    st.session_state.study_manifest   = manifest
    st.session_state.study_topics     = topics
    st.session_state.study_summaries  = summaries
    st.session_state.study_cards      = all_cards
    st.session_state.study_leitner    = deck
    st.session_state.study_pdf_names  = saved

    progress.progress(1.0, text="Done!")

    from study.ai_generate import _can_use_api, get_ai_label
    ai_note = f" · {get_ai_label()}" if _can_use_api() else " · Offline mode"
    st.success(
        f"✅ **{saved[0]}** indexed successfully!  \n"
        f"**{len(topics)}** topics · **{len(all_cards)}** cards{ai_note}"
    )

    # OCR warning
    for doc, stats in get_ocr_stats(sid).items():
        if stats["mean_confidence"] < 0.80:
            st.warning(
                f"⚠️ **{doc}** is a scanned PDF — "
                f"OCR confidence: {stats['mean_confidence']:.0%}. "
                f"Low-confidence pages: {stats['low_pages'] or 'none'}."
            )


# ── Tab: Summary ─────────────────────────────────────────────────────────────

def study_tab_summary():
    _study_session_state()
    st.subheader("📝 Topic Summary")

    topics    = st.session_state.study_topics
    summaries = st.session_state.study_summaries
    dirs      = st.session_state.study_dirs

    if not topics:
        st.info("Upload a PDF first (Upload tab).")
        return

    topic_titles = [t["title"] for t in topics]
    sel = st.selectbox("Select topic", topic_titles)
    topic = next(t for t in topics if t["title"] == sel)
    s     = summaries.get(topic["id"], {})

    st.markdown(f"**Pages {topic['page_start']} – {topic['page_end']}**")

    for b in s.get("bullets", []):
        col1, col2 = st.columns([10, 1])
        with col1:
            st.markdown(f"• {b['text']}")
        with col2:
            if st.button("🔍", key=f"src_{b['page']}_{b['text'][:10]}",
                         help="View source page"):
                _render_source(
                    b.get("doc", ""), b.get("page"), b.get("bbox"), dirs
                )

    if s.get("key_numbers"):
        st.markdown("#### 🔢 Key Numbers")
        rows = [{
            "Value":  n["value"],
            "Unit":   n["unit"],
            "Period": n["period"],
            "Page":   n["page"],
        } for n in s["key_numbers"]]
        st.dataframe(rows, width="stretch")


# ── Tab: Flashcards ──────────────────────────────────────────────────────────

def study_tab_flashcards():
    _study_session_state()
    st.subheader("🃏 Flashcards")

    cards = st.session_state.study_cards
    dirs  = st.session_state.study_dirs

    if not cards:
        st.info("Upload a PDF first (Upload tab).")
        return

    from study.ai_generate import _can_use_api
    ai_count = sum(1 for c in cards if c.get("source") == "ai")
    ext_count = len(cards) - ai_count
    if _can_use_api() and ai_count > 0:
        st.success(f"☁️ {ai_count} AI-generated cards + 📚 {ext_count} extractive cards")
    else:
        st.caption(f"📚 {ext_count} extractive cards (offline mode)")

    topics    = st.session_state.study_topics
    topic_map = {t["id"]: t["title"] for t in topics}

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        topic_filter = st.selectbox(
            "Filter by topic",
            ["All"] + list(topic_map.values()),
        )
    with col2:
        diff_filter = st.selectbox("Difficulty", ["All", "easy", "medium", "hard"])
    with col3:
        type_filter = st.selectbox("Type", ["All", "concept", "key_number", "cloze"])

    shuffle = st.toggle("Shuffle", value=False)

    filtered = [c for c in cards
                if (topic_filter == "All" or topic_map.get(c["topic_id"]) == topic_filter)
                and (diff_filter == "All" or c.get("difficulty") == diff_filter)
                and (type_filter == "All" or c.get("type") == type_filter)]

    if shuffle:
        import random
        random.shuffle(filtered)

    if not filtered:
        st.info("No cards match the selected filters.")
        return

    st.caption(f"{len(filtered)} card(s) shown")

    for card in filtered:
        with st.container(border=True):
            col_q, col_flip = st.columns([9, 1])
            with col_q:
                st.markdown(f"**{card['front']}**")
                st.caption(
                    f"{card.get('type','')} · {card.get('difficulty','')} · "
                    f"p.{card.get('page','?')}"
                )
            with col_flip:
                flipped = st.session_state.study_flip.get(card["id"], False)
                if st.button("↩" if flipped else "👁", key=f"flip_{card['id']}"):
                    st.session_state.study_flip[card["id"]] = not flipped
                    st.rerun()

            if st.session_state.study_flip.get(card["id"]):
                st.success(f"**Answer:** {card['back']}")
                if not card.get("verified"):
                    st.warning("⚠️ This number could not be verified in the source.")

                deck = st.session_state.study_leitner
                if deck:
                    col_k, col_r = st.columns(2)
                    with col_k:
                        if st.button("✅ I knew it", key=f"knew_{card['id']}"):
                            deck.answer(card["id"], True)
                    with col_r:
                        if st.button("🔁 Review again", key=f"review_{card['id']}"):
                            deck.answer(card["id"], False)

                if st.button("📄 Show source", key=f"show_{card['id']}"):
                    _render_source(
                        card.get("doc", ""), card.get("page"),
                        card.get("bbox"), dirs
                    )

            st.divider()

    # Exports
    st.markdown("#### 📥 Export")
    from study.export import to_csv, to_anki_tsv, to_pdf as cards_to_pdf
    ec1, ec2, ec3 = st.columns(3)
    with ec1:
        st.download_button("CSV", to_csv(filtered),
                           "flashcards.csv", "text/csv")
    with ec2:
        st.download_button("Anki TSV", to_anki_tsv(filtered),
                           "flashcards.tsv", "text/tab-separated-values")
    with ec3:
        st.download_button("Print PDF",
                           cards_to_pdf(filtered, "My Flashcards"),
                           "flashcards.pdf", "application/pdf")


# ── Tab: Quiz ────────────────────────────────────────────────────────────────

def study_tab_quiz():
    _study_session_state()
    st.subheader("🧠 Quiz Mode")

    cards    = st.session_state.study_cards
    deck     = st.session_state.study_leitner
    dirs     = st.session_state.study_dirs
    topics   = st.session_state.study_topics
    summaries= st.session_state.study_summaries

    if not cards or not deck:
        st.info("Upload a PDF first (Upload tab).")
        return

    from study.ai_generate import _can_use_api, generate_quiz_api
    api_on = _can_use_api()

    # ── Mode selector ─────────────────────────────────────────────────────────
    col_mode, col_score, col_btn = st.columns([2, 2, 2])
    with col_mode:
        quiz_mode = st.radio(
            "Quiz type",
            ["AI Generated" if api_on else "AI (no key)", "Flashcard Based"],
            horizontal=True,
            disabled=not api_on,
            key="quiz_mode_radio",
        )
        use_ai = api_on and quiz_mode == "AI Generated"
        if api_on:
            st.caption("☁️ Claude-powered" if use_ai else "📚 Extractive")
        else:
            st.caption("💻 Offline (no API key)")

    score = st.session_state.study_quiz_score
    with col_score:
        st.metric("Score", f"{score['correct']}/{score['total']}")

    with col_btn:
        next_btn = st.button("▶ Next Question", type="primary",
                              width="stretch")

    st.divider()

    # ── Generate or fetch next question ──────────────────────────────────────
    if next_btn:
        import random
        st.session_state.study_quiz_ans = None

        if use_ai and topics:
            # Pick a random topic, generate AI question
            topic   = random.choice(topics)
            summary = summaries.get(topic["id"], {})
            with st.spinner("Claude is generating a question…"):
                ai_qs = generate_quiz_api(topic, summary, n_questions=1)
            if ai_qs:
                q = ai_qs[0]
                q["card_id"] = f"ai_{topic['id']}_{int(time.time())}"
                st.session_state.study_quiz_q = q
            else:
                # Fallback to card-based
                card = random.choice(cards)
                st.session_state.study_quiz_q = deck.make_quiz_question(card, cards)
        else:
            # Extractive: pick from due cards
            pool = deck.due_cards() or cards
            card = random.choice(pool)
            st.session_state.study_quiz_q = deck.make_quiz_question(card, cards)

        st.rerun()

    q = st.session_state.study_quiz_q
    if not q:
        st.info("Click **▶ Next Question** to start the quiz.")
        return

    # ── Render question ───────────────────────────────────────────────────────
    is_ai_q = q.get("source") == "ai"
    st.markdown(f"### {q['question']}")
    if is_ai_q:
        st.caption(f"☁️ AI-generated · Topic: {q.get('topic_id','')} · p.{q.get('page','?')}")
    else:
        st.caption(f"📚 Flashcard-based · {q.get('doc','?')} p.{q.get('page','?')}")

    # ── Show result if already answered ──────────────────────────────────────
    prev_ans = st.session_state.get("study_quiz_ans")
    if prev_ans is not None:
        if prev_ans == q["answer"]:
            st.success(f"✅ Correct! **{q['answer']}**")
        else:
            st.error(f"❌ Incorrect. You chose: **{prev_ans}**")
            st.warning(f"Correct answer: **{q['answer']}**")
        if is_ai_q and q.get("explanation"):
            st.info(f"💡 {q['explanation']}")
        if dirs and q.get("doc") and q.get("page"):
            _render_source(q.get("doc",""), q.get("page"), q.get("bbox"), dirs)
        return

    # ── Answer choices ────────────────────────────────────────────────────────
    choices = q.get("choices", [])
    choice_labels = [f"{chr(65+i)}. {c}" for i, c in enumerate(choices)]
    selected = st.radio("Your answer:", choice_labels, index=None,
                        key=f"quiz_radio_{q.get('card_id','')}_{len(choices)}")

    submit = st.button("Submit ✔", disabled=selected is None,
                       width="stretch", type="primary")

    if submit and selected is not None:
        chosen  = selected[3:]   # strip "A. " prefix
        correct = chosen == q["answer"]
        score["total"] += 1
        if correct:
            score["correct"] += 1
            if not is_ai_q:
                deck.answer(q["card_id"], True)
        else:
            if not is_ai_q:
                deck.answer(q["card_id"], False)
        st.session_state.study_quiz_ans = chosen
        st.rerun()


def study_tab_videos():
    _study_session_state()
    st.subheader("▶️ Recommended Videos")

    topics = st.session_state.study_topics
    if not topics:
        st.info("Upload a PDF first (Upload tab).")
        return

    from study.youtube import recommendations_for_topic, YOUTUBE_API_KEY as _ytkey

    if _ytkey:
        st.caption("☁️ YouTube Data API v3 — real video results")
    else:
        st.caption("🔗 YouTube search links (set YOUTUBE_API_KEY for real results)")

    st.info("📌 Recommendations are external and not verified against your document.")

    for topic in topics:
        with st.expander(f"🎬 {topic['title']} (p.{topic['page_start']}–{topic['page_end']})"):
            recs = recommendations_for_topic(topic, n=3)

            if not recs or recs[0].get("mode") == "blocked":
                st.warning("Video recommendations are blocked in Government offline mode.")
                continue

            for r in recs:
                if r.get("mode") == "B" and r.get("title"):
                    # Real API result — show rich card
                    col_info, col_link = st.columns([4, 1])
                    with col_info:
                        st.markdown(f"**{r['title']}**")
                        if r.get("channel"):
                            st.caption(f"📺 {r['channel']}"
                                       + (f" · ⏱ {r['duration']}" if r.get("duration") else ""))
                    with col_link:
                        st.link_button("Watch ▶", r["url"], width="stretch")
                else:
                    # Mode A — search link
                    st.link_button(r["title"], r["url"], width="stretch")


def study_tab_ask():
    _study_session_state()
    st.subheader("❓ Ask Your PDF")

    sid  = st.session_state.study_session_id
    dirs = st.session_state.study_dirs

    if not sid or not dirs:
        st.info("Upload a PDF first (Upload tab).")
        return

    q = st.text_input("Ask a question about your uploaded PDF")
    if not q.strip():
        return

    if st.button("Ask ▶", type="primary"):
        from tracerag.engine import Engine
        session_engine = Engine(str(dirs["index"]), str(dirs["pdfs"]))
        with st.spinner("Searching your document…"):
            result = session_engine.answer(f"study_{sid[:8]}", q.strip())

        status = result.get("status", "")
        answer = result.get("answer", "")
        docs   = _doc_list(result)
        pages  = _page_list(result)

        if status == "refuse":
            st.warning(
                f"🔴 Not found in your document. "
                f"Reason: {result.get('reason_codes', ['unknown'])}"
            )
        elif status == "conflict":
            st.warning(f"⚠️ Conflicting values found: **{answer}**")
        else:
            st.success(f"**{answer}**")

        if docs and pages:
            st.caption(f"Source: {docs[0]} p.{pages[0]}")
            bbox = result.get("bbox")
            if isinstance(bbox, str):
                try:
                    bbox = json.loads(bbox)
                except Exception:
                    bbox = None
            img = render_page_bytes(str(dirs["pdfs"] / docs[0]), pages[0], bbox)
            if img:
                st.image(img, width="stretch")

        receipt = result.get("audit_receipt", "")
        if receipt:
            st.caption(f"Receipt: `{receipt}`")


# ── Tab: Progress ────────────────────────────────────────────────────────────

def study_tab_progress():
    _study_session_state()
    st.subheader("📈 Study Progress")

    deck   = st.session_state.study_leitner
    topics = st.session_state.study_topics

    if not deck:
        st.info("Upload a PDF first (Upload tab).")
        return

    prog = deck.progress()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total cards",   prog["total"])
    col2.metric("Graduated",     prog["graduated"])
    col3.metric("% Graduated",   f"{prog['pct_graduated']}%")

    st.markdown("#### Cards per Leitner Box")
    box_df = [{"Box": f"Box {b}", "Cards": n}
              for b, n in prog["by_box"].items()]
    st.bar_chart({row["Box"]: row["Cards"] for row in box_df})

    st.markdown("#### By Topic")
    topic_prog = deck.topic_progress()
    topic_map  = {t["id"]: t["title"] for t in topics}
    rows = []
    for tid, tp in topic_prog.items():
        rows.append({
            "Topic":      topic_map.get(tid, tid),
            "Cards":      tp["cards"],
            "Mean Box":   tp["mean_box"],
            "Graduated":  tp["graduated"],
        })
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), width="stretch")

    score = st.session_state.study_quiz_score
    st.markdown("#### Quiz Score")
    total = score["total"]
    if total:
        pct = round(score["correct"] / total * 100, 1)
        st.metric("Correct", f"{score['correct']}/{total}",
                  delta=f"{pct}%")
    else:
        st.info("No quiz attempts yet.")

    if st.button("🔄 Advance session (new study round)"):
        deck.advance_session()
        st.success(f"Session {deck.session} started.")



# ── Universal PDF upload + Knowledge Q&A tab (all roles) ──────────────────────

def study_tab_my_pdfs():
    """
    Available to ALL roles (including Government offline).
    Upload your own PDF → get topic summary → ask questions from it.
    Government mode: fully local, no external calls.
    """
    _study_session_state()

    user   = st.session_state.get("user", {})
    is_gov = user.get("offline", False)

    st.subheader("📚 My PDFs — Upload & Ask")
    if is_gov:
        st.info("🔒 Government mode: processing is fully local. No data leaves this machine.")
    else:
        st.info("🌐 Online mode: your PDF is processed locally in a private session.")

    from study.upload import (
        new_session_id, session_dirs, validate_pdf, save_upload,
        ingest_session_pdf, sha256_of, log_upload, delete_session,
        cleanup_expired_sessions, get_ocr_stats, UploadError,
        MAX_UPLOAD_MB, MAX_PAGES,
    )

    cleanup_expired_sessions()

    # Show AI mode status
    from study.ai_generate import _can_use_api as _ai_ok
    if _ai_ok():
        st.success("☁️ **AI mode active** — Claude will generate richer summaries, "
                   "flashcards and quiz questions from your PDF.")
    else:
        st.info("💻 **Offline mode** — Extractive summaries and flashcards (no API key).")

    st.caption(f"Max {MAX_UPLOAD_MB} MB · Max {MAX_PAGES} pages · PDF only")

    # Upload widget
    uploaded_files = st.file_uploader(
        "Drop your PDF here",
        type=["pdf"],
        accept_multiple_files=True,
        key="my_pdfs_uploader",
    )

    col_proc, col_del = st.columns([3, 1])
    with col_proc:
        process = st.button("📥 Process PDF", type="primary",
                             width="stretch",
                             disabled=not uploaded_files)
    with col_del:
        can_del = bool(st.session_state.get("study_session_id"))
        if st.button("🗑 Delete files", width="stretch", disabled=not can_del):
            delete_session(st.session_state["study_session_id"])
            for k in list(st.session_state.keys()):
                if k.startswith("study_"):
                    del st.session_state[k]
            _study_session_state()
            st.success("Files deleted.")
            st.rerun()

    if process and uploaded_files:
        sid  = new_session_id()
        dirs = session_dirs(sid)
        prog = st.progress(0.0, text="Validating…")
        errors, saved = [], []

        for i, uf in enumerate(uploaded_files):
            prog.progress((i / len(uploaded_files)) * 0.3,
                          text=f"Validating {uf.name}…")
            data = uf.read()
            try:
                validate_pdf(data, uf.name)
                save_upload(sid, uf.name, data)
                log_upload(sid, uf.name, sha256_of(data), str(dirs["index"]))
                saved.append(uf.name)
            except UploadError as e:
                errors.append(f"**{uf.name}**: {e}")

        for err in errors:
            st.error(err)

        if saved:
            # Step 1: Index
            prog.progress(0.4, text="Indexing PDF…")
            try:
                import logging
                logging.getLogger("tracerag.ingest").setLevel(logging.WARNING)
                ingest_session_pdf(sid, saved[0])
                prog.progress(0.55, text="Indexed. Extracting topics…")
            except Exception as e:
                st.error(f"❌ Indexing failed: {e}")
                return

            # Step 2: Topics
            from study.topics import extract_topics, _attach_regions
            from study.summarise import summarise_topic
            from study.flashcards import generate_cards
            from study.leitner import LeitnerDeck

            topics, summaries, all_cards = [], {}, []
            for fname in saved:
                pdf_path  = str(dirs["pdfs"] / fname)
                reg_jsonl = str(dirs["index"] / "regions.jsonl")
                try:
                    t = extract_topics(pdf_path, reg_jsonl)
                    if not t:
                        t = [{
                            "id": "t00", "title": fname.replace(".pdf",""),
                            "page_start": 1, "page_end": 999,
                            "source": "fallback", "region_ids": [], "page_texts": {},
                        }]
                        t = _attach_regions(t, reg_jsonl)
                    topics.extend(t)
                except Exception as e:
                    st.error(f"❌ Topic extraction failed: {e}")
                    continue

            if not topics:
                st.error("❌ No topics could be extracted. Try a different PDF.")
                return

            # Step 3: Summaries + cards
            for idx, topic in enumerate(topics):
                pct = 0.60 + (idx / max(len(topics), 1)) * 0.35
                prog.progress(pct, text=f"Summarising: {topic['title'][:35]}…")
                try:
                    s = summarise_topic(topic, str(dirs["index"]), saved[0])
                    summaries[topic["id"]] = s
                except Exception as e:
                    summaries[topic["id"]] = {
                        "title": topic["title"], "bullets": [], "key_numbers": []
                    }
                try:
                    c = generate_cards(topic, summaries[topic["id"]],
                                       str(dirs["index"]), saved[0],
                                       str(dirs["pdfs"] / saved[0]))
                    all_cards.extend(c)
                except Exception:
                    pass

            st.session_state.study_session_id = sid
            st.session_state.study_dirs       = dirs
            st.session_state.study_topics     = topics
            st.session_state.study_summaries  = summaries
            st.session_state.study_cards      = all_cards
            st.session_state.study_leitner    = LeitnerDeck(all_cards)
            st.session_state.study_pdf_names  = saved
            prog.progress(1.0, text="Done!")

            from study.ai_generate import _can_use_api, get_ai_label
            ai_note = f" · {get_ai_label()}" if _can_use_api() else ""
            st.success(
                f"✅ **{saved[0]}** ready!  "
                f"**{len(topics)}** topics · **{len(all_cards)}** cards{ai_note}"
            )

            # OCR warning
            for doc, stats in get_ocr_stats(sid).items():
                if stats["mean_confidence"] < 0.80:
                    st.warning(
                        f"⚠️ **{doc}** is scanned — "
                        f"OCR confidence: {stats['mean_confidence']:.0%}. "
                        f"Low-confidence pages: {stats['low_pages'] or 'none'}."
                    )

    # ── If PDFs are already loaded, show summary + Q&A ────────────────────────
    topics   = st.session_state.get("study_topics", [])
    summaries= st.session_state.get("study_summaries", {})
    dirs     = st.session_state.get("study_dirs")

    if not topics:
        st.info("Upload a PDF above to get started.")
        return

    st.divider()
    st.subheader("📋 Topics & Summary")

    topic_titles = [t["title"] for t in topics]
    sel_title    = st.selectbox("Select a topic", topic_titles,
                                key="my_pdfs_topic_sel")
    sel_topic    = next(t for t in topics if t["title"] == sel_title)
    s            = summaries.get(sel_topic["id"], {})

    st.caption(f"Pages {sel_topic['page_start']} – {sel_topic['page_end']}")

    for b_idx, b in enumerate(s.get("bullets", [])):
        col_txt, col_src = st.columns([11, 1])
        with col_txt:
            st.markdown(f"• {b['text']}")
        with col_src:
            # Key uses topic id + bullet index to guarantee uniqueness
            btn_key = f"mypdf_src_{sel_topic['id']}_{b_idx}"
            if st.button("🔍", key=btn_key, help="View source page"):
                if dirs and b.get("doc") and b.get("page"):
                    pdf_path = dirs["pdfs"] / b["doc"]
                    if pdf_path.exists():
                        img = render_page_bytes(str(pdf_path), b["page"],
                                                b.get("bbox"), dpi=120)
                        if img:
                            st.image(img, width="stretch")

    if s.get("key_numbers"):
        with st.expander("🔢 Key Numbers"):
            st.dataframe([{
                "Value": n["value"], "Unit": n["unit"],
                "Period": n["period"], "Page": n["page"],
            } for n in s["key_numbers"]], width="stretch")

    # ── Knowledge Q&A from the uploaded PDF ──────────────────────────────────
    st.divider()
    st.subheader("❓ Ask Questions from Your PDF")
    st.caption("Questions are answered using only the content of your uploaded PDF.")

    q_input = st.text_input("Type your question", placeholder="e.g. What is the main conclusion?",
                             key="my_pdfs_question")
    ask_btn = st.button("Ask ▶", key="my_pdfs_ask_btn", type="primary")

    if ask_btn and q_input.strip() and dirs:
        from tracerag.engine import Engine
        session_engine = Engine(str(dirs["index"]), str(dirs["pdfs"]))
        with st.spinner("Searching your document…"):
            result = session_engine.answer(
                f"mypdf_{int(time.time()*1000)}", q_input.strip()
            )

        status = result.get("status", "")
        answer = result.get("answer", "")

        if status == "refuse":
            reason = ", ".join(result.get("reason_codes", ["unknown"]))
            st.warning(f"🔴 Not found in your PDF. Reason: `{reason}`")
            st.warning(f"⚠️ Conflicting values: **{answer}**")
        else:
            st.success(f"**Answer:** {answer}")

        # Show source page with highlight
        docs  = result.get("doc")
        pages = result.get("page")
        bbox  = result.get("bbox")
        if isinstance(docs,  list): docs  = docs[0]  if docs  else None
        if isinstance(pages, list): pages = pages[0] if pages else None
        if isinstance(bbox, str):
            try: bbox = json.loads(bbox)
            except: bbox = None

        if docs and pages and dirs:
            pdf_path = dirs["pdfs"] / docs
            if pdf_path.exists():
                st.caption(f"Source: **{docs}** · Page **{pages}**")
                img = render_page_bytes(str(pdf_path), pages, bbox, dpi=130)
                if img:
                    st.image(img, caption=f"Page {pages}", width="stretch")

        receipt = result.get("audit_receipt", "")
        if receipt:
            st.caption(f"Receipt: `{receipt}`")

    # ── Flashcards from this PDF ──────────────────────────────────────────────
    all_cards = st.session_state.get("study_cards", [])
    if all_cards:
        st.divider()
        st.subheader("🃏 Flashcards from This PDF")
        st.caption(f"{len(all_cards)} cards generated. Flip to see answers.")

        # Show top 5 for this topic
        topic_cards = [c for c in all_cards
                       if c.get("topic_id") == sel_topic["id"]][:5]

        for card in topic_cards:
            with st.container(border=True):
                col_q, col_flip = st.columns([9, 1])
                with col_q:
                    st.markdown(f"**{card['front']}**")
                    st.caption(f"{card.get('type','')} · p.{card.get('page','?')}")
                with col_flip:
                    flipped = st.session_state.study_flip.get(card["id"], False)
                    if st.button("👁" if not flipped else "↩",
                                 key=f"mypdf_flip_{card['id']}"):
                        st.session_state.study_flip[card["id"]] = not flipped
                        st.rerun()
                if st.session_state.study_flip.get(card["id"]):
                    st.success(f"**Answer:** {card['back']}")
                    if not card.get("verified"):
                        st.warning("⚠️ Could not verify this number in source.")

        from study.export import to_csv, to_anki_tsv
        ec1, ec2 = st.columns(2)
        with ec1:
            st.download_button("⬇ CSV", to_csv(all_cards),
                               "my_cards.csv", "text/csv")
        with ec2:
            st.download_button("⬇ Anki TSV", to_anki_tsv(all_cards),
                               "my_cards.tsv", "text/tab-separated-values")


if __name__ == "__main__":
    main()
