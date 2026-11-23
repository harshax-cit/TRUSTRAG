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


if __name__ == "__main__":
    main()
