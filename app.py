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
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

# ── config & auth (imported first so government guard activates early) ────────
from config import (
    is_government_mode, get_mode_label, get_ai_label,
    index_dir as _cfg_index_dir, pdf_dir as _cfg_pdf_dir,
    ROLE_TABS, GovernmentModeViolation,
)
from auth import authenticate, get_role_info, is_authorised, AuthError

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
    st.sidebar.title("TraceRAG")
    st.sidebar.caption("Multimodal RAG with Explainability")

    # ── Environment indicator ─────────────────────────────────────────────────
    if is_government_mode():
        st.sidebar.error(
            "🔒 **OFFLINE — Government Secure Environment**\n\n"
            "All processing is local. No external API calls."
        )
    else:
        from tracerag.llm import is_online as _llm_online
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
        if st.sidebar.button("Logout", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # Quick question selector
    questions = load_jsonl(QUESTIONS)
    options   = ["— custom question —"] + [q["question"][:80] for q in questions]
    sel    = st.sidebar.selectbox("Practice questions", options)
    custom = st.sidebar.text_area("Or type your question", height=90)

    if sel != "— custom question —":
        q_text = next(q["question"] for q in questions if q["question"][:80] == sel)
    else:
        q_text = custom.strip()

    run    = st.sidebar.button("Ask ▶", type="primary", use_container_width=True)
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
                        st.image(img, use_container_width=True)

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
            st.dataframe(pd.DataFrame(timeline_rows), use_container_width=True)
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
            st.image(img, caption=f"Page {pages[0]} (highlighted)", use_container_width=True)

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
                st.image(img, use_container_width=True)

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
    check = st.button("Check claim ✔", use_container_width=True)

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
                st.image(img, use_container_width=True)

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
            st.dataframe(df_ledger, use_container_width=True)
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

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="TraceRAG",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Login gate — single page for all roles
    if not st.session_state.get("user"):
        _show_login()
        return

    user   = st.session_state["user"]
    role   = user["role"]
    is_gov = user.get("offline", False)   # True only for government role

    # Paths are scoped to the user's environment
    _idx_dir = ROOT / "data" / "gov_index" if is_gov else ROOT / "data" / "index"
    _pdf_dir = ROOT / "data" / "gov_pdfs"  if is_gov else ROOT / "data" / "raw" / "pdfs"

    q_text, run, strict = sidebar()

    if "result"   not in st.session_state: st.session_state.result   = None
    if "question" not in st.session_state: st.session_state.question = ""

    if run and q_text:
        with st.spinner("Searching documents…"):
            from tracerag.engine import Engine
            _eng = Engine(str(_idx_dir), str(_pdf_dir))
            qid  = f"ui_{int(time.time()*1000)}"
            st.session_state.result   = _eng.answer(qid, q_text, strict=strict)
            st.session_state.question = q_text

    result   = st.session_state.result
    question = st.session_state.question
    allowed  = ROLE_TABS.get(role, [])

    if is_gov:
        _government_dashboard(result, question, allowed, _idx_dir)
    else:
        _online_dashboard(result, question, allowed)


# ── Login screen (single page, login + create account) ───────────────────────

def _show_login():
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown(
            "<h1 style='text-align:center'>📄 TraceRAG</h1>"
            "<p style='text-align:center;color:grey'>Multimodal RAG with Explainability</p>",
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
                                                   use_container_width=True,
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

            with st.expander("👥 Demo accounts"):
                st.markdown(
                    "| Username | Password | Role | Env |\n"
                    "|---|---|---|---|\n"
                    "| `government` | `gov-secure-2024` | Government | 🔒 Offline |\n"
                    "| `analyst` | `analyst-pass` | Policy Analyst | 🌐 Online |\n"
                    "| `journalist` | `press-pass` | Journalist | 🌐 Online |\n"
                    "| `student` | `learn-2024` | Student | 🌐 Online |\n"
                    "| `checker` | `verify-pass` | Fact-Checker | 🌐 Online |\n"
                    "| `auditor` | `audit-admin` | Auditor / Admin | 🌐 Online |"
                )

        # ── Create Account tab ────────────────────────────────────────────────
        with tab_register:
            st.info("Government accounts must be provisioned by an administrator.")
            with st.form("register_form"):
                reg_name  = st.text_input("Full Name", placeholder="Your Name")
                reg_user  = st.text_input("Username",  placeholder="choose-a-username")
                reg_pass  = st.text_input("Password",  type="password",
                                           placeholder="at least 6 characters")
                reg_pass2 = st.text_input("Confirm Password", type="password")
                reg_role  = st.selectbox("Role", [
                    "student", "analyst", "journalist", "factchecker"
                ], format_func=lambda r: {
                    "student":     "🎓 Student",
                    "analyst":     "📊 Policy Analyst",
                    "journalist":  "📰 Journalist",
                    "factchecker": "🔍 Fact-Checker",
                }.get(r, r))
                reg_btn = st.form_submit_button("Create Account →",
                                                 use_container_width=True,
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
            st.image(img, use_container_width=True)


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
                                use_container_width=True,
                                disabled=not uploaded)
    with col2:
        delete_btn = st.button("🗑 Delete my files",
                               use_container_width=True,
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
        st.dataframe(rows, use_container_width=True)


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
                              use_container_width=True)

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
                       use_container_width=True, type="primary")

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
                        st.link_button("Watch ▶", r["url"], use_container_width=True)
                else:
                    # Mode A — search link
                    st.link_button(r["title"], r["url"], use_container_width=True)


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
                import json as _json
                try:
                    bbox = _json.loads(bbox)
                except Exception:
                    bbox = None
            img = render_page_bytes(str(dirs["pdfs"] / docs[0]), pages[0], bbox)
            if img:
                st.image(img, use_container_width=True)

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
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

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
                             use_container_width=True,
                             disabled=not uploaded_files)
    with col_del:
        can_del = bool(st.session_state.get("study_session_id"))
        if st.button("🗑 Delete files", use_container_width=True, disabled=not can_del):
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
                            st.image(img, use_container_width=True)

    if s.get("key_numbers"):
        with st.expander("🔢 Key Numbers"):
            st.dataframe([{
                "Value": n["value"], "Unit": n["unit"],
                "Period": n["period"], "Page": n["page"],
            } for n in s["key_numbers"]], use_container_width=True)

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
                    st.image(img, caption=f"Page {pages}", use_container_width=True)

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
