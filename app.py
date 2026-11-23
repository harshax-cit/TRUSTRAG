"""
app.py – TraceRAG Streamlit UI

Five lenses (tabs):
  1. Analyst    – highlighted page, side-by-side conflict, revision timeline, CSV export
  2. Journalist – safe-to-publish badge, copyable citation with receipt ID
  3. Student    – plain-language explanation, glossary, suggested follow-ups
  4. Fact-checker – paste a claim → Supported / Contradicted / Not in collection
  5. Auditor    – chain integrity badge, refusal ledger, decision mix, tamper demo

Answer, page, bbox and status are identical in every lens.
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

# ── paths ────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
INDEX_DIR  = ROOT / "data" / "index"
PDF_DIR    = ROOT / "data" / "raw" / "pdfs"
QUESTIONS  = ROOT / "data" / "raw" / "practice_questions.jsonl"
ANSWERS    = ROOT / "data" / "raw" / "practice_answers.jsonl"

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
    return sqlite3.connect(str(INDEX_DIR / "facts.db"), check_same_thread=False)

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

    # Online / offline indicator
    from tracerag.llm import is_online
    mode = "☁️ Cloud LLM active" if is_online() else "💻 Offline (local only)"
    st.sidebar.info(mode)

    # Quick question selector
    questions = load_jsonl(QUESTIONS)
    options = ["— custom question —"] + [q["question"][:80] for q in questions]
    sel = st.sidebar.selectbox("Practice questions", options)
    custom = st.sidebar.text_area("Or type your question", height=90)

    if sel != "— custom question —":
        q_text = next(q["question"] for q in questions if q["question"][:80] == sel)
    else:
        q_text = custom.strip()

    run = st.sidebar.button("Ask ▶", type="primary", use_container_width=True)
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

    q_text, run, strict = sidebar()

    # Persistent result in session state
    if "result" not in st.session_state:
        st.session_state.result = None
    if "question" not in st.session_state:
        st.session_state.question = ""

    if run and q_text:
        with st.spinner("Searching documents…"):
            st.session_state.result   = ask(q_text, strict=strict)
            st.session_state.question = q_text

    result   = st.session_state.result
    question = st.session_state.question

    # Tabs
    tabs = st.tabs([
        "📊 Analyst",
        "📰 Journalist",
        "🎓 Student",
        "🔍 Fact-checker",
        "🔐 Auditor",
        "📤 Upload",
        "📝 Summary",
        "🃏 Flashcards",
        "🧠 Quiz",
        "▶️ Videos",
        "❓ Ask",
        "📈 Progress",
    ])

    with tabs[0]:
        if result:
            lens_analyst(result, question)
        else:
            st.info("Ask a question using the sidebar to get started.")

    with tabs[1]:
        if result:
            lens_journalist(result, question)
        else:
            st.info("Ask a question using the sidebar to get started.")

    with tabs[2]:
        if result:
            lens_student(result, question)
        else:
            st.info("Ask a question using the sidebar to get started.")

    with tabs[3]:
        lens_factchecker()

    with tabs[4]:
        lens_auditor()

    with tabs[5]:
        study_tab_upload()

    with tabs[6]:
        study_tab_summary()

    with tabs[7]:
        study_tab_flashcards()

    with tabs[8]:
        study_tab_quiz()

    with tabs[9]:
        study_tab_videos()

    with tabs[10]:
        study_tab_ask()

    with tabs[11]:
        study_tab_progress()


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

    progress.progress(0.4, text="Parsing and indexing…")
    try:
        manifest = ingest_session_pdf(sid, saved[0])
    except Exception as e:
        st.error(f"Indexing failed: {e}")
        return

    progress.progress(0.9, text="Building topics…")

    from study.topics import extract_topics
    topics     = []
    summaries  = {}
    all_cards  = []

    for fname in saved:
        pdf_path  = str(dirs["pdfs"] / fname)
        reg_jsonl = str(dirs["index"] / "regions.jsonl")
        t = extract_topics(pdf_path, reg_jsonl)
        topics.extend(t)

        from study.summarise import summarise_topic
        from study.flashcards import generate_cards
        for topic in t:
            s = summarise_topic(topic, str(dirs["index"]), fname)
            summaries[topic["id"]] = s
            cards = generate_cards(topic, s, str(dirs["index"]),
                                   fname, pdf_path)
            all_cards.extend(cards)

    from study.leitner import LeitnerDeck
    deck = LeitnerDeck(all_cards)

    # Store in session state
    st.session_state.study_session_id = sid
    st.session_state.study_dirs       = dirs
    st.session_state.study_manifest   = manifest
    st.session_state.study_topics     = topics
    st.session_state.study_summaries  = summaries
    st.session_state.study_cards      = all_cards
    st.session_state.study_leitner    = deck
    st.session_state.study_pdf_names  = saved

    progress.progress(1.0, text="Done!")

    st.success(
        f"✅ Indexed {len(saved)} file(s) · "
        f"{len(topics)} topics · {len(all_cards)} cards"
    )

    # OCR warning
    ocr = get_ocr_stats(sid)
    for doc, stats in ocr.items():
        mean_conf = stats["mean_confidence"]
        low_pages = stats["low_pages"]
        if mean_conf < 0.80:
            st.warning(
                f"⚠️ **{doc}** is a scanned PDF. "
                f"Mean OCR confidence: {mean_conf:.0%}. "
                f"Low-confidence pages: {low_pages or 'none'}. "
                "Some facts may be mis-read."
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

    cards = st.session_state.study_cards
    deck  = st.session_state.study_leitner
    dirs  = st.session_state.study_dirs

    if not cards or not deck:
        st.info("Upload a PDF first (Upload tab).")
        return

    due   = deck.due_cards()
    score = st.session_state.study_quiz_score

    col_score, col_btn = st.columns([2, 1])
    with col_score:
        st.metric("Session score",
                  f"{score['correct']}/{score['total']}",
                  delta=None)
    with col_btn:
        next_btn = st.button("Next question ▶", type="primary",
                              use_container_width=True)

    if next_btn:
        import random
        pool = due if due else cards
        card = random.choice(pool)
        st.session_state.study_quiz_q     = deck.make_quiz_question(card, cards)
        st.session_state.study_quiz_ans   = None   # clear previous answer
        st.rerun()

    q = st.session_state.study_quiz_q
    if not q:
        st.info("Click 'Next question ▶' to start.")
        return

    # Show question
    st.markdown(f"### {q['question']}")
    st.caption(f"Card type: {cards[0].get('type','') if cards else ''} · "
               f"Source: {q.get('doc','?')} p.{q.get('page','?')}")
    st.divider()

    # Show result if already answered this question
    prev_ans = st.session_state.get("study_quiz_ans")
    if prev_ans is not None:
        if prev_ans == q["answer"]:
            st.success(f"✅ Correct! **{q['answer']}**")
        else:
            st.error(f"❌ Incorrect. You chose: **{prev_ans}**")
            st.info(f"Correct answer: **{q['answer']}**")
        # Show source page
        if dirs and q.get("doc") and q.get("page"):
            _render_source(q.get("doc",""), q.get("page"),
                           q.get("bbox"), dirs)
        return

    # Render choices as radio (avoids duplicate key issues with buttons)
    choice_labels = [f"{chr(65+i)}. {c}" for i, c in enumerate(q["choices"])]
    selected = st.radio("Choose your answer:", choice_labels,
                        index=None, key=f"quiz_radio_{q['card_id']}")

    submit = st.button("Submit ✔", disabled=selected is None,
                       use_container_width=True)

    if submit and selected is not None:
        # Extract the actual answer text (strip "A. " prefix)
        chosen = selected[3:]   # remove "X. "
        correct = chosen == q["answer"]

        score["total"] += 1
        if correct:
            score["correct"] += 1
            deck.answer(q["card_id"], True)
        else:
            deck.answer(q["card_id"], False)

        st.session_state.study_quiz_ans = chosen
        st.rerun()


# ── Tab: Videos ──────────────────────────────────────────────────────────────

def study_tab_videos():
    _study_session_state()
    st.subheader("▶️ Recommended Videos")

    topics = st.session_state.study_topics
    if not topics:
        st.info("Upload a PDF first (Upload tab).")
        return

    from study.youtube import recommendations_for_topic, YOUTUBE_API_KEY as _ytkey

    mode_label = "☁️ YouTube API" if _ytkey else "🔗 Search links (no API key)"
    st.caption(f"Mode: {mode_label} · Recommendations are external and not from your document.")

    for topic in topics:
        with st.expander(f"🎬 {topic['title']}"):
            recs = recommendations_for_topic(topic, n=3)
            for r in recs:
                st.markdown(f"[{r['title']}]({r['url']})")
                if r.get("channel"):
                    st.caption(f"Channel: {r['channel']}")
            st.caption(recs[0]["note"] if recs else "")


# ── Tab: Ask (Q&A over uploaded PDF) ─────────────────────────────────────────

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


if __name__ == "__main__":
    main()
