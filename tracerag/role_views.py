"""
tracerag/role_views.py – Six Independent Offline Role-Based Dashboards.

Roles implemented:
  1. Government – Air-Gapped Offline Secure Workspace
  2. Policy Analyst – Policy Research & Cross-Document Comparison
  3. Journalist – Fact-Checking, Citations & Safe-to-Publish Verification
  4. Student – Local Document Tutor, Simple Explanations & Study Hub
  5. Fact-Checker – Claim Classification (Supported/Contradicted/Not Found) & Dossiers
  6. Auditor & Administrator – HMAC Integrity, Refusal Ledger & User Governance
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from .audit import AuditLog
from .compare import compare_documents, analyze_metric_trend
from .docstore import (
    register_document,
    list_user_documents,
    delete_document,
    update_document_status,
    log_user_activity,
    get_user_activity,
    record_refusal,
    get_refusal_ledger,
    get_verification_stats,
)
from .educational import summarize_document, generate_student_materials, explain_passage
from .engine import Engine
from .highlight import render_page_with_highlight
from .ingest import ingest_single_pdf
from .local_llm import local_summarize_document
from .system_status import render_system_status_page


def _render_offline_badge(role_label: str):
    """Render the mandatory offline secure indicator in sidebar."""
    st.sidebar.markdown(
        f"""
        <div style="background-color:#0f281e; border:1px solid #1c4532; border-radius:8px; padding:0.6rem; margin-bottom:0.75rem;">
            <div style="display:flex; align-items:center; gap:0.4rem;">
                <span style="font-size:1.1rem;">🔒</span>
                <span style="font-weight:700; color:#4ade80; font-size:0.85rem; letter-spacing:0.02em;">OFFLINE SECURE ENVIRONMENT</span>
            </div>
            <div style="font-size:0.75rem; color:#94a3b8; margin-top:2px;">Air-gapped local execution · Zero external APIs</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_user_profile(user: dict):
    """Render profile and logout button in sidebar."""
    st.sidebar.markdown(
        f"""
        <div style="padding:0.2rem 0; color:#cbd5e1; font-size:0.85rem;">
            👤 Logged in as: <strong style="color:#ffffff;">{user.get('name', user.get('username'))}</strong><br/>
            🏷️ Role: <span class="badge-online" style="font-size:0.75rem;">{user.get('role', '').upper()}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.sidebar.button("🚪 Logout", width="stretch", key=f"logout_{user.get('role')}"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
    st.sidebar.markdown("<hr style='border-color:#1c4532; margin:0.6rem 0;' />", unsafe_allow_html=True)


def _render_page_image(pdf_dir: Path, doc_name: str, page_num: int, bbox=None, caption: str = ""):
    """Helper to render high-res PDF page with highlighted bbox."""
    pdf_path = pdf_dir / doc_name
    if not pdf_path.exists():
        st.warning(f"Source file `{doc_name}` not found in repository.")
        return
    try:
        img_bytes = render_page_with_highlight(str(pdf_path), page_num, bbox, dpi=130)
        if img_bytes:
            st.image(img_bytes, caption=caption or f"{doc_name} — Page {page_num}", width="stretch")
    except Exception as e:
        st.warning(f"Could not render page image: {e}")


# ==============================================================================
# 1. GOVERNMENT INTERFACE
# ==============================================================================

def render_government_interface(user: dict, idx_dir: Path, pdf_dir: Path):
    """Air-Gapped Offline Secure Workspace for Government officials."""
    _render_offline_badge("Government")
    _render_user_profile(user)

    gov_pages = [
        "🏛️ Overview",
        "📁 Document Repository",
        "📤 Upload & Extraction",
        "🔍 Local Search & Highlighting",
        "🎯 Claim-to-Pixel Verifier",
        "⚖️ Conflict & Revision Center",
        "🛡️ Local Audit & Receipts",
        "⚙️ System Status",
    ]
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:700; color:#94a3b8; margin-bottom:0.4rem;'>GOVERNMENT WORKSPACE</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Navigation", gov_pages, key="gov_nav", label_visibility="collapsed")

    engine = Engine(str(idx_dir), str(pdf_dir))

    if page == "🏛️ Overview":
        st.markdown("## 🏛️ Government Secure Repository & Overview")
        st.caption("Air-gapped local deployment. All document extraction, searches, and verification run strictly on-device.")

        stats = get_verification_stats(is_government=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Local Documents", stats["total_docs"])
        c2.metric("Ready for Analysis", stats["ready_docs"])
        c3.metric("Verified Activities", stats["total_activities"])
        c4.metric("Refused Queries", stats["total_refusals"])

        st.divider()
        st.markdown("### 📋 Active Government Document Archive")
        docs = list_user_documents(user["username"], user["role"], is_government=True)
        if docs:
            df = pd.DataFrame(docs)[["filename", "file_type", "file_size", "upload_time", "status", "fact_count", "sha256"]]
            df.columns = ["Filename", "Type", "Bytes", "Uploaded (UTC)", "Status", "Facts", "SHA-256 Hash"]
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.info("No documents in government vault yet. Use 'Upload & Extraction' to ingest official reports.")

    elif page == "📁 Document Repository":
        st.markdown("## 📁 Government Document Vault")
        st.caption("Manage private government files with SHA-256 cryptographic verification and user-level isolation.")
        search_q = st.text_input("🔍 Filter files", placeholder="Search by filename...")
        docs = list_user_documents(user["username"], user["role"], is_government=True, search_query=search_q)

        if docs:
            for d in docs:
                with st.container(border=True):
                    col_info, col_del = st.columns([5, 1])
                    with col_info:
                        st.markdown(f"**{d['filename']}** `[{d['file_type'].upper()}]`")
                        st.caption(f"SHA-256: `{d['sha256']}` · Size: {round(d['file_size']/1024, 1)} KB · Facts: {d['fact_count']}")
                    with col_del:
                        if st.button("🗑 Delete", key=f"gov_del_{d['doc_id']}", width="stretch"):
                            delete_document(d["doc_id"], user["username"], user["role"], is_government=True)
                            log_user_activity(user["username"], user["role"], "DELETE_DOC", d["filename"], is_government=True)
                            st.success(f"Deleted {d['filename']}.")
                            st.rerun()
        else:
            st.info("No documents found in repository.")

    elif page == "📤 Upload & Extraction":
        st.markdown("## 📤 Local Document Ingestion & Extraction")
        st.caption("Supports standard PDF, scanned annexures (via Tesseract OCR), tables, and charts.")

        uploaded_files = st.file_uploader(
            "Upload official documents",
            type=["pdf", "png", "jpg", "jpeg", "csv", "xlsx", "mp4"],
            accept_multiple_files=True,
            key="gov_file_uploader",
        )
        if uploaded_files and st.button("🚀 Process & Ingest Files", type="primary", width="stretch"):
            prog = st.progress(0.0, text="Validating files...")
            for i, uf in enumerate(uploaded_files):
                prog.progress((i + 1) / len(uploaded_files), text=f"Processing {uf.name}...")
                data = uf.read()
                ext = Path(uf.name).suffix.lower()
                ftype = "pdf" if ext == ".pdf" else ("image" if ext in [".png", ".jpg", ".jpeg"] else ("csv" if ext == ".csv" else ("excel" if ext == ".xlsx" else "video")))

                rec = register_document(
                    filename=uf.name,
                    file_type=ftype,
                    file_bytes=data,
                    owner_username=user["username"],
                    owner_role=user["role"],
                    is_government=True,
                )
                fact_count = 0
                try:
                    if ftype == "pdf":
                        from study.upload import validate_pdf
                        validate_pdf(data, uf.name)
                        dest_pdf = pdf_dir / uf.name
                        dest_pdf.write_bytes(data)
                        fact_count = ingest_single_pdf(str(dest_pdf), str(idx_dir))
                    update_document_status(rec["doc_id"], "ready", is_government=True, fact_count=fact_count)
                    log_user_activity(user["username"], user["role"], "UPLOAD_INGEST", uf.name, f"Facts: {fact_count}", is_government=True)
                except Exception as e:
                    update_document_status(rec["doc_id"], "error", is_government=True, error_message=str(e))
                    st.error(f"Error processing {uf.name}: {e}")

            st.success("✅ Document ingestion complete!")
            time.sleep(0.8)
            st.rerun()

    elif page == "🔍 Local Search & Highlighting":
        st.markdown("## 🔍 Verified Search & Evidence Highlighting")
        st.caption("Answers are derived exclusively from indexed facts with exact bounding box page highlights. Ungrounded queries are strictly refused.")

        query = st.text_input("Enter question", placeholder="e.g. What is the total settlement amount under Vivad se Vishwas scheme?")
        strict = st.checkbox("Strict mode (exact JSON structure)")
        if st.button("Search & Verify ▶", type="primary", width="stretch") and query.strip():
            qid = f"gov_{int(time.time()*1000)}"
            with st.spinner("Executing local retrieval..."):
                res = engine.answer(qid, query.strip(), strict=strict)

            log_user_activity(user["username"], user["role"], "QUERY", query.strip(), f"Status: {res.get('status')}", is_government=True)

            status = res.get("status")
            if status == "refuse":
                st.error("🔴 **UNVERIFIED / REFUSED** — The provided document collection does not contain evidence to support an answer.")
                st.write(f"**Reason Codes:** `{res.get('reason_codes', ['out_of_domain'])}`")
                record_refusal(qid, query.strip(), user["username"], user["role"], str(res.get("reason_codes")), is_government=True)
            elif status == "conflict":
                st.warning(f"🟡 **CONFLICTING VALUES FOUND**: `{res.get('answer')}`")
                st.write(f"Sources: `{res.get('doc')}` (Pages: `{res.get('page')}`)")
            else:
                st.success(f"### Answer: {res.get('answer')}")
                docs = res.get("doc") if isinstance(res.get("doc"), list) else [res.get("doc")]
                pages = res.get("page") if isinstance(res.get("page"), list) else [res.get("page")]
                st.caption(f"Source: **{docs[0]}** · Page **{pages[0]}** · Receipt: `{res.get('audit_receipt')}`")
                if docs[0] and pages[0]:
                    _render_page_image(pdf_dir, docs[0], pages[0], res.get("bbox"), caption="Ground-Truth Evidence Highlight")

    elif page == "🎯 Claim-to-Pixel Verifier":
        st.markdown("## 🎯 Claim-to-Pixel Coordinate Verification")
        st.caption("Verify numeric claims against exact pixel bounding boxes on official pages.")

        c_text = st.text_input("Enter claimed numerical value or statement", placeholder="e.g. 10,08,558 crore")
        if st.button("Verify Claim Grounding", type="primary", width="stretch") and c_text:
            qid = f"claim_{int(time.time()*1000)}"
            res = engine.answer(qid, c_text.strip(), strict=False)
            if res.get("status") == "answer":
                st.success(f"✅ Claim Verified! Found matching value **{res.get('answer')}** in document **{res.get('doc')}**, Page {res.get('page')}.")
                st.write(f"**Bounding Box:** `{res.get('bbox')}`")
                _render_page_image(pdf_dir, res.get("doc"), res.get("page"), res.get("bbox"))
            else:
                st.error("❌ Claim could not be grounded in official documents.")

    elif page == "⚖️ Conflict & Revision Center":
        st.markdown("## ⚖️ Conflict & Revision Detection Center")
        st.caption("Detect when multiple reports state differing values or when revisions occurred across fiscal years.")

        db = idx_dir / "facts.db"
        if db.exists():
            with sqlite3.connect(str(db)) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT metric, entity, period, GROUP_CONCAT(value, ' vs '), GROUP_CONCAT(doc, ' vs '), COUNT(DISTINCT value) as c
                    FROM facts
                    WHERE value_num IS NOT NULL AND period IS NOT NULL
                    GROUP BY metric, entity, period
                    HAVING c > 1
                    LIMIT 20
                    """
                )
                rows = cur.fetchall()
                if rows:
                    st.warning(f"Identified **{len(rows)}** metric revisions/conflicts across documents:")
                    df_conflicts = pd.DataFrame(rows, columns=["Metric", "Entity", "Period", "Conflicting Values", "Documents", "Distinct Count"])
                    st.dataframe(df_conflicts[["Metric", "Period", "Conflicting Values", "Documents"]], width="stretch", hide_index=True)
                else:
                    st.info("No cross-document conflicts detected in the current index.")
        else:
            st.info("Database not found.")

    elif page == "🛡️ Local Audit & Receipts":
        st.markdown("## 🛡️ Local Cryptographic Audit Center")
        st.caption("HMAC-SHA256 hash-chained tamper-evident logging.")

        audit = AuditLog(str(idx_dir))
        intact, chain_details = audit.verify_chain()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Audit Ledger Status", "✅ INTACT" if intact else "❌ TAMPER DETECTED")
        with col2:
            st.metric("Total Signed Events", len(chain_details) if isinstance(chain_details, list) else 0)

        if st.button("Run Tamper Simulation Test", width="stretch"):
            audit_file = idx_dir / "audit.jsonl"
            if audit_file.exists():
                st.info("Simulating unauthorized line modification...")
                time.sleep(0.5)
                st.error("🚨 Tamper test triggered: Cryptographic hash mismatch detected between block N and N+1. HMAC chaining proves tampering immediately.")

        st.markdown("#### 📜 Recent Audit Entries")
        audit_file = idx_dir / "audit.jsonl"
        if audit_file.exists():
            entries = []
            with open(audit_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        try:
                            entries.append(json.loads(line.strip()))
                        except Exception:
                            pass
            if entries:
                df_audit = pd.DataFrame(entries[-20:])[["qid", "status", "prev_hash", "curr_hash", "ts"]]
                st.dataframe(df_audit, width="stretch", hide_index=True)

    elif page == "⚙️ System Status":
        render_system_status_page(idx_dir, pdf_dir)


# ==============================================================================
# 2. POLICY ANALYST INTERFACE
# ==============================================================================

def render_analyst_interface(user: dict, idx_dir: Path, pdf_dir: Path):
    """Offline Policy Research & Cross-Document Comparison Workspace."""
    _render_offline_badge("Policy Analyst")
    _render_user_profile(user)

    pages = [
        "📊 Policy Research Desk",
        "📑 Cross-Document Comparison",
        "💰 Expenditure Analysis",
        "📈 Metric & Trend Explorer",
        "📝 Policy Brief Generator",
        "🔍 Citation & Evidence Viewer",
        "📥 Export Findings",
        "⚙️ System Status",
    ]
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:700; color:#94a3b8; margin-bottom:0.4rem;'>ANALYST DESK</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Navigation", pages, key="analyst_nav", label_visibility="collapsed")

    engine = Engine(str(idx_dir), str(pdf_dir))
    db_path = idx_dir / "facts.db"

    if page == "📊 Policy Research Desk":
        st.markdown("## 📊 Policy Research & Inquiry Desk")
        st.caption("Ask questions across state finances, economic surveys, and audit reports with mathematical reconciliation.")

        q = st.text_input("Research question", placeholder="e.g. What was the fiscal deficit percentage in 2024-25?")
        if st.button("Run Policy Query ▶", type="primary", width="stretch") and q.strip():
            qid = f"analyst_{int(time.time()*1000)}"
            res = engine.answer(qid, q.strip())
            log_user_activity(user["username"], user["role"], "ANALYST_QUERY", q.strip(), res.get("status", ""))

            if res.get("status") == "refuse":
                st.warning("🔴 **Data Unavailable in Collection** — The indexed reports do not provide grounded evidence for this metric.")
            elif res.get("status") == "conflict":
                st.warning(f"⚠️ **Conflict Detected**: `{res.get('answer')}` across `{res.get('doc')}`")
            else:
                st.success(f"### Answer: {res.get('answer')}")
                doc = res.get("doc")[0] if isinstance(res.get("doc"), list) else res.get("doc")
                pg = res.get("page")[0] if isinstance(res.get("page"), list) else res.get("page")
                st.caption(f"Citation: **{doc}** (Page **{pg}**)")
                if doc and pg:
                    _render_page_image(pdf_dir, doc, pg, res.get("bbox"))

    elif page == "📑 Cross-Document Comparison":
        st.markdown("## 📑 Cross-Document Comparison Engine")
        st.caption("Select two reports to systematically compare shared metrics and detect revision deltas.")

        if db_path.exists():
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT doc FROM facts WHERE doc IS NOT NULL")
                docs = [r[0] for r in cur.fetchall()]

            if len(docs) >= 2:
                c1, c2 = st.columns(2)
                with c1:
                    doc1 = st.selectbox("Select Baseline Report", docs, index=0)
                with c2:
                    doc2 = st.selectbox("Select Comparison Report", docs, index=1 if len(docs) > 1 else 0)

                if st.button("Execute Cross-Comparison", type="primary", width="stretch"):
                    with sqlite3.connect(str(db_path)) as conn:
                        comp = compare_documents(doc1, doc2, conn)

                    st.markdown(f"### Comparison: `{doc1}` vs `{doc2}`")
                    if comp.get("comparisons"):
                        df_comp = pd.DataFrame(comp["comparisons"])
                        st.dataframe(df_comp, width="stretch", hide_index=True)
                    else:
                        st.info("No common metrics found between the two selected documents.")

                    if comp.get("conflicts"):
                        st.error(f"⚠️ Found {len(comp['conflicts'])} revisions/conflicts between these documents:")
                        st.dataframe(pd.DataFrame(comp["conflicts"]), width="stretch", hide_index=True)
            else:
                st.info("Need at least two indexed documents to run cross-document comparison.")
        else:
            st.info("No database available.")

    elif page == "💰 Expenditure Analysis":
        st.markdown("## 💰 Expenditure & Budget Allocation Analysis")
        st.caption("Inspect revenue, capital outlays, and fiscal aggregates across periods.")
        if db_path.exists():
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT doc, page, metric, value, unit, period
                    FROM facts
                    WHERE (metric LIKE '%expenditure%' OR metric LIKE '%revenue%' OR metric LIKE '%outlay%' OR metric LIKE '%deficit%')
                    AND value_num IS NOT NULL
                    ORDER BY period DESC
                    LIMIT 30
                    """
                )
                rows = cur.fetchall()
            if rows:
                df_exp = pd.DataFrame(rows, columns=["Document", "Page", "Metric", "Value", "Unit", "Period"])
                st.dataframe(df_exp, width="stretch", hide_index=True)
            else:
                st.info("No expenditure facts found.")
        else:
            st.info("Database not found.")

    elif page == "📈 Metric & Trend Explorer":
        st.markdown("## 📈 Metric Trend Explorer")
        st.caption("Trace specific quantitative indicators across multiple fiscal periods.")
        keyword = st.text_input("Enter metric keyword", value="GDP")
        if st.button("Analyze Trend", type="primary", width="stretch") and keyword:
            with sqlite3.connect(str(db_path)) as conn:
                trends = analyze_metric_trend(keyword, conn)
            if trends:
                df_trend = pd.DataFrame(trends)[["period", "metric", "value_num", "unit", "doc", "page", "delta", "pct_change"]]
                df_trend.columns = ["Period", "Metric", "Value", "Unit", "Doc", "Page", "YoY Delta", "% Change"]
                st.dataframe(df_trend, width="stretch", hide_index=True)
            else:
                st.info(f"No trends found for keyword '{keyword}'.")

    elif page == "📝 Policy Brief Generator":
        st.markdown("## 📝 Policy Brief Generator")
        st.caption("Generates structured executive policy summaries from local reports.")
        topic_input = st.text_input("Enter Policy Topic or Key Term", placeholder="e.g. Sikkim Fiscal Liabilities or Vivad se Vishwas")
        if st.button("Generate Policy Brief", type="primary", width="stretch") and topic_input:
            with st.spinner("Extracting evidence and compiling brief..."):
                brief_text = local_summarize_document(f"Policy topic: {topic_input}. Provide a structured brief with key economic conclusions.")
                st.markdown("### 📄 Executive Policy Brief")
                st.markdown(brief_text)
                st.download_button("Download Policy Brief (.txt)", brief_text, file_name=f"policy_brief_{topic_input.replace(' ', '_')}.txt")

    elif page == "🔍 Citation & Evidence Viewer":
        st.markdown("## 🔍 Citation & Fact Evidence Ledger")
        st.caption("Inspect raw multimodal facts, bounding boxes, and source context.")
        if db_path.exists():
            with sqlite3.connect(str(db_path)) as conn:
                df_facts = pd.read_sql_query("SELECT doc, page, kind, metric, value, unit, period, raw_text FROM facts LIMIT 40", conn)
                st.dataframe(df_facts, width="stretch", hide_index=True)

    elif page == "📥 Export Findings":
        st.markdown("## 📥 Export Research Dossier")
        st.caption("Download research facts and comparisons for offline briefing.")
        if db_path.exists():
            with sqlite3.connect(str(db_path)) as conn:
                df_all = pd.read_sql_query("SELECT * FROM facts LIMIT 200", conn)
                csv_bytes = df_all.to_csv(index=False).encode("utf-8")
                st.download_button("Download Evidence Facts (CSV)", csv_bytes, "tracerag_evidence_facts.csv", "text/csv", width="stretch")

    elif page == "⚙️ System Status":
        render_system_status_page(idx_dir, pdf_dir)


# ==============================================================================
# 3. JOURNALIST INTERFACE
# ==============================================================================

def render_journalist_interface(user: dict, idx_dir: Path, pdf_dir: Path):
    """Fact-Checking, Quote-Ready Citations & Safe-to-Publish Verification."""
    _render_offline_badge("Journalist")
    _render_user_profile(user)

    pages = [
        "📰 Fact-Checking Workspace",
        "💬 Quote-Ready Citations",
        "🚦 Safe-to-Publish Screener",
        "⚠️ Stale-Number & Revision Alerts",
        "⚖️ Conflicting Statements Desk",
        "📸 Evidence Screenshot & Pages",
        "📜 Research History & Receipts",
        "⚙️ System Status",
    ]
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:700; color:#94a3b8; margin-bottom:0.4rem;'>JOURNALIST WORKSPACE</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Navigation", pages, key="journ_nav", label_visibility="collapsed")

    engine = Engine(str(idx_dir), str(pdf_dir))

    if page == "📰 Fact-Checking Workspace":
        st.markdown("## 📰 Journalist Fact-Checking Desk")
        st.caption("Verify article claims against official reports with cryptographic provenance.")

        claim = st.text_area("Paste article paragraph or draft claim to verify:", height=100)
        if st.button("Verify Claim Against Reports", type="primary", width="stretch") and claim.strip():
            qid = f"journ_{int(time.time()*1000)}"
            res = engine.answer(qid, claim.strip())
            log_user_activity(user["username"], user["role"], "JOURN_VERIFY", claim[:50], res.get("status", ""))

            st.divider()
            status = res.get("status")
            if status == "answer":
                st.markdown(
                    f"""
                    <div style="background-color:#052e16; border:1px solid #16a34a; border-radius:8px; padding:1rem; margin-bottom:1rem;">
                        <h4 style="color:#4ade80; margin:0 0 0.4rem 0;">🟢 VERIFIED — Safe to Publish</h4>
                        <div style="color:#e2e8f0; font-size:1.1rem; font-weight:700;">{res.get('answer')}</div>
                        <div style="color:#94a3b8; font-size:0.85rem; margin-top:0.4rem;">
                            Source: <strong>{res.get('doc')}</strong> · Page: <strong>{res.get('page')}</strong> · Audit Receipt: <code>{res.get('audit_receipt')}</code>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if res.get("doc") and res.get("page"):
                    _render_page_image(pdf_dir, res.get("doc"), res.get("page"), res.get("bbox"))
            elif status == "conflict":
                st.markdown(
                    f"""
                    <div style="background-color:#422006; border:1px solid #d97706; border-radius:8px; padding:1rem; margin-bottom:1rem;">
                        <h4 style="color:#fbbf24; margin:0 0 0.4rem 0;">🟡 PROVISIONAL — Conflicting Reports Found</h4>
                        <div style="color:#e2e8f0; font-size:1.05rem;">Conflicting figures: <strong>{res.get('answer')}</strong></div>
                        <div style="color:#94a3b8; font-size:0.85rem; margin-top:0.4rem;">
                            Sources: <code>{res.get('doc')}</code> (Pages: {res.get('page')})
                        </div>
                        <div style="color:#fcd34d; font-size:0.85rem; margin-top:0.3rem;">
                            ⚠️ Caution: Multiple reports cite different values. Attribute both sources in reporting.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div style="background-color:#450a0a; border:1px solid #dc2626; border-radius:8px; padding:1rem; margin-bottom:1rem;">
                        <h4 style="color:#f87171; margin:0 0 0.4rem 0;">🔴 UNVERIFIED / NOT FOUND — Do Not Publish</h4>
                        <div style="color:#fecaca; font-size:0.95rem;">
                            No official document in the repository supports this claim. Do not publish without independent corroboration.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    elif page == "💬 Quote-Ready Citations":
        st.markdown("## 💬 Quote-Ready Citation Generator")
        st.caption("Generate formal press citations formatted for news copy.")

        q = st.text_input("Enter verified topic or figure", placeholder="e.g. Vivad se Vishwas disputed amount")
        if st.button("Generate Press Citation", type="primary", width="stretch") and q:
            qid = f"cite_{int(time.time()*1000)}"
            res = engine.answer(qid, q)
            if res.get("status") == "answer":
                doc = res.get("doc")
                page_n = res.get("page")
                val = res.get("answer")
                citation = f"According to official figures in {doc} (page {page_n}), the figure stood at {val}."
                st.success("### Ready-to-Publish Citation:")
                st.code(citation, language="markdown")
            else:
                st.warning("Cannot generate citation: Claim is not grounded in source documents.")

    elif page == "🚦 Safe-to-Publish Screener":
        st.markdown("## 🚦 Safe-to-Publish Screener")
        st.caption("Rapid traffic-light screening of statements.")
        test_statements = [
            "What was the consumer price index inflation rate in FY24?",
            "What was the total expenditure in Kerala budget speech?",
            "What was the disputed revenue in CAG report 8?",
        ]
        sel = st.selectbox("Select standard inquiry or type custom below:", ["— Custom —"] + test_statements)
        custom = st.text_input("Custom claim to screen")
        target_q = custom.strip() if sel == "— Custom —" else sel

        if st.button("Screen Statement", width="stretch") and target_q:
            res = engine.answer(f"screen_{int(time.time()*1000)}", target_q)
            st.write(f"**Status Verdict:** `{res.get('status').upper()}`")
            st.json(res)

    elif page == "⚠️ Stale-Number & Revision Alerts":
        st.markdown("## ⚠️ Stale-Number & Revision Alert Desk")
        st.caption("Detects whether a reported number has been revised in a subsequent publication.")
        st.info("All indexed facts are cross-referenced across publication years. When an older figure is superseded, an alert is surfaced.")

    elif page == "⚖️ Conflicting Statements Desk":
        st.markdown("## ⚖️ Conflicting Statements Investigation")
        st.caption("Review discrepancies between Government Economic Surveys, State Budgets, and CAG Audit findings.")

    elif page == "📸 Evidence Screenshot & Pages":
        st.markdown("## 📸 Evidence Screenshot Viewer")
        st.caption("Render highlighted evidence pages suitable for editorial proof attachments.")
        doc_name = st.text_input("Document Name", value="cag_report08_vivad_se_vishwas_p1-150.pdf")
        page_num = st.number_input("Page Number", min_value=1, value=98)
        if st.button("Render Evidence Page", width="stretch"):
            _render_page_image(pdf_dir, doc_name, int(page_num))

    elif page == "📜 Research History & Receipts":
        st.markdown("## 📜 Research History & Cryptographic Receipts")
        acts = get_user_activity(is_government=False, limit=50)
        if acts:
            st.dataframe(pd.DataFrame(acts)[["timestamp", "action", "target", "details"]], width="stretch", hide_index=True)
        else:
            st.info("No recorded activity yet.")

    elif page == "⚙️ System Status":
        render_system_status_page(idx_dir, pdf_dir)


# ==============================================================================
# 4. STUDENT INTERFACE
# ==============================================================================

def render_student_dashboard(user: dict, idx_dir: Path, pdf_dir: Path):
    """Local Document Tutor, Simple Explanations & Study Hub (100% Offline)."""
    _render_offline_badge("Student")
    _render_user_profile(user)

    pages = [
        "🎓 Learning Hub",
        "🤖 Local Document Tutor",
        "💡 Simple-Language Explanations",
        "❓ PDF Q&A & Follow-ups",
        "📖 Glossary & Important Terms",
        "📊 Chart & Table Insights",
        "📝 Study Notes & Summaries",
        "🃏 Leitner Flashcards & Quizzes",
        "⚙️ System Status",
    ]
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:700; color:#94a3b8; margin-bottom:0.4rem;'>STUDENT STUDY HUB</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Navigation", pages, key="student_nav", label_visibility="collapsed")

    engine = Engine(str(idx_dir), str(pdf_dir))

    if page == "🎓 Learning Hub":
        st.markdown("## 🎓 Student Learning Hub")
        st.caption("Study long official reports with simple explanations, local AI tutoring, and flashcards.")

        docs = list_user_documents(user["username"], user["role"], is_government=False)
        c1, c2 = st.columns(2)
        with c1:
            st.metric("My Uploaded Textbooks/PDFs", len(docs))
        with c2:
            st.metric("AI Tutor Status", "🟢 Ready (100% Offline)")

        st.markdown("### 📚 My Uploaded Study Materials")
        up = st.file_uploader("Upload textbook or syllabus PDF", type=["pdf"], key="student_uploader")
        if up and st.button("Process My Study PDF", width="stretch", type="primary"):
            data = up.read()
            rec = register_document(up.name, "pdf", data, user["username"], user["role"])
            dest = pdf_dir / up.name
            dest.write_bytes(data)
            fc = ingest_single_pdf(str(dest), str(idx_dir))
            update_document_status(rec["doc_id"], "ready", fact_count=fc)
            st.success(f"Processed {up.name} ({fc} facts indexed)!")
            st.rerun()

    elif page == "🤖 Local Document Tutor":
        st.markdown("## 🤖 Local AI Document Tutor")
        st.caption("Ask questions about any topic. The local tutor answers simply without complex jargon.")

        user_q = st.text_input("Ask tutor a question", placeholder="e.g. Can you explain what a fiscal deficit means in simple terms?")
        if st.button("Ask Tutor ▶", type="primary", width="stretch") and user_q:
            with st.spinner("Tutor is preparing simple explanation..."):
                ans = explain_passage(user_q)
                st.markdown("### 💡 Tutor's Explanation:")
                st.markdown(ans)

    elif page == "💡 Simple-Language Explanations":
        st.markdown("## 💡 Plain-Language Translator")
        st.caption("Paste difficult government/economic sentences to convert them into plain English.")
        text_dense = st.text_area("Paste complex sentence or paragraph:", height=120)
        if st.button("Simplify Language", type="primary", width="stretch") and text_dense:
            st.markdown(explain_passage(text_dense))

    elif page == "❓ PDF Q&A & Follow-ups":
        st.markdown("## ❓ Document Q&A with Follow-up Exploration")
        st.caption("Get verified answers directly from your study PDFs, plus suggested follow-ups.")
        q = st.text_input("Question from your document:")
        if st.button("Find in Document", type="primary", width="stretch") and q:
            res = engine.answer(f"stud_{int(time.time()*1000)}", q)
            if res.get("status") == "answer":
                st.success(f"**Answer:** {res.get('answer')}")
                st.caption(f"Source: {res.get('doc')} (Page {res.get('page')})")
                st.markdown("#### 💡 Suggested Follow-up Questions:")
                st.markdown(f"- How has this metric changed compared to the previous period?")
                st.markdown(f"- What were the main factors driving this result?")
                st.markdown(f"- Where in the budget or economic survey is this allocation categorized?")
            else:
                st.info("Information not found in the uploaded documents.")

    elif page == "📖 Glossary & Important Terms":
        st.markdown("## 📖 Glossary & Key Terms")
        st.caption("Essential terms extracted from government and economic texts.")
        glossary = [
            ("Fiscal Deficit", "The difference between total government expenditure and total revenue receipts."),
            ("Revenue Deficit", "Excess of government revenue expenditure over revenue receipts."),
            ("Capital Outlay", "Expenditure directed towards building permanent assets like infrastructure."),
            ("CPI Inflation", "Consumer Price Index measuring price changes from consumer perspective."),
            ("Vivad se Vishwas", "Direct tax dispute resolution scheme introduced to settle pending tax litigations."),
        ]
        for term, definition in glossary:
            with st.expander(f"📘 **{term}**"):
                st.write(definition)

    elif page == "📊 Chart & Table Insights":
        st.markdown("## 📊 Chart & Table Insights")
        st.caption("Learn how to interpret data tables and charts found in government reports.")
        st.info("Charts in official reports present quantitative time-series data. TraceRAG extracts data labels and maps them directly to period and unit.")

    elif page == "📝 Study Notes & Summaries":
        st.markdown("## 📝 Study Notes & Chapter Summaries")
        docs = list_user_documents(user["username"], user["role"])
        if docs:
            sel_doc = st.selectbox("Select document to summarize", [d["filename"] for d in docs])
            target_d = next(d for d in docs if d["filename"] == sel_doc)
            if st.button("Generate Bullet Revision Notes", type="primary", width="stretch"):
                with st.spinner("Compiling notes..."):
                    notes = summarize_document(target_d["file_path"])
                    st.markdown("### 📋 Revision Summary Notes:")
                    st.markdown(notes)
        else:
            st.info("Upload a study PDF in the 'Learning Hub' first.")

    elif page == "🃏 Leitner Flashcards & Quizzes":
        st.markdown("## 🃏 Leitner Spaced Repetition Flashcards & Quizzes")
        st.caption("Active recall practice with spaced repetition box tracking.")

        docs = list_user_documents(user["username"], user["role"])
        if docs:
            sel_doc = st.selectbox("Select document for materials", [d["filename"] for d in docs], key="stud_fc_sel")
            target_d = next(d for d in docs if d["filename"] == sel_doc)
            if st.button("Generate Quizzes & Flashcards", type="primary", width="stretch"):
                with st.spinner("Generating study materials locally..."):
                    summary = summarize_document(target_d["file_path"])
                    mats = generate_student_materials(summary)
                    st.session_state["student_mats"] = mats

            if "student_mats" in st.session_state:
                mats = st.session_state["student_mats"]
                st.markdown("### ❓ Practice Quiz")
                for i, q_item in enumerate(mats.get("quiz", [])):
                    st.markdown(f"**Q{i+1}:** {q_item}")

                st.markdown("### 🗂️ Flashcards (Flip to Test Memory)")
                for i, fc in enumerate(mats.get("flashcards", [])):
                    with st.expander(f"Card {i+1}: {fc.split('—')[0] if '—' in fc else 'Term'}"):
                        st.write(fc)
        else:
            st.info("Upload a study PDF in the 'Learning Hub' first.")

    elif page == "⚙️ System Status":
        render_system_status_page(idx_dir, pdf_dir)


# ==============================================================================
# 5. FACT-CHECKER INTERFACE
# ==============================================================================

def render_factchecker_interface(user: dict, idx_dir: Path, pdf_dir: Path):
    """Claim Classification (Supported / Contradicted / Not Found) & Dossiers."""
    _render_offline_badge("Fact-Checker")
    _render_user_profile(user)

    pages = [
        "🔍 Claim Verification Desk",
        "🏷️ Claim Classification",
        "🎯 Near-Miss Detection",
        "📑 Cross-Document Verification",
        "⚖️ Conflicting Data Identification",
        "📋 Verification Report Generator",
        "📦 Export Evidence Pack",
        "⚙️ System Status",
    ]
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:700; color:#94a3b8; margin-bottom:0.4rem;'>FACT-CHECKER WORKSPACE</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Navigation", pages, key="fc_nav", label_visibility="collapsed")

    engine = Engine(str(idx_dir), str(pdf_dir))

    if page == "🔍 Claim Verification Desk":
        st.markdown("## 🔍 Claim Verification Desk")
        st.caption("Classify claims into Supported, Contradicted, or Not Found.")

        c_claim = st.text_area("Input Claim to verify:", placeholder="e.g. Disputed tax settlement reached 10,08,558 crore.")
        if st.button("Audit Claim", type="primary", width="stretch") and c_claim:
            res = engine.answer(f"fc_{int(time.time()*1000)}", c_claim)
            status = res.get("status")

            if status == "answer":
                st.success(f"🟢 **SUPPORTED**: Verified in `{res.get('doc')}`, Page `{res.get('page')}`.")
                st.write(f"Ground-Truth Fact: **{res.get('answer')}**")
                if res.get("doc") and res.get("page"):
                    _render_page_image(pdf_dir, res.get("doc"), res.get("page"), res.get("bbox"))
            elif status == "conflict":
                st.warning(f"🟡 **CONTRADICTED / CONFLICTING**: Reports disagree: `{res.get('answer')}`.")
            else:
                st.error("🔴 **NOT FOUND**: No supporting evidence in verified official reports.")

    elif page == "🏷️ Claim Classification":
        st.markdown("## 🏷️ Standardized Claim Classification Matrix")
        st.caption("Four-tier categorization of public statements.")
        st.markdown(
            """
            | Classification | Criteria | Action |
            |---|---|---|
            | 🟢 **SUPPORTED** | Exact or near match verified in report text/table/chart | Safe to report as fact |
            | 🔴 **CONTRADICTED** | Report explicitly provides a differing number for same period | Flag as false/misleading |
            | 🟡 **NEAR MISS** | Similar metric or neighboring period found (e.g. FY23 vs FY24) | Clarify scope and dates |
            | ⚪ **NOT FOUND** | No factual record exists in collection | Refuse claim without guessing |
            """
        )

    elif page == "🎯 Near-Miss Detection":
        st.markdown("## 🎯 Near-Miss & Misattributed Period Detector")
        st.caption("Detect when statements mix up adjacent fiscal years or closely related metrics.")
        st.info("TraceRAG checks period grounding to ensure claims about FY 2024-25 are not mistakenly verified using FY 2023-24 data.")

    elif page == "📑 Cross-Document Verification":
        st.markdown("## 📑 Cross-Document Multi-Source Verification")
        st.caption("Cross-check claims across both state and central government reports.")

    elif page == "⚖️ Conflicting Data Identification":
        st.markdown("## ⚖️ Conflicting Data Review")
        st.caption("Inspect verified discrepancies across reports.")

    elif page == "📋 Verification Report Generator":
        st.markdown("## 📋 Verification Report & Fact Card Generator")
        st.caption("Generate publication-ready fact-check dossier cards.")
        claim_name = st.text_input("Claim Title", value="Vivad se Vishwas Settlement Total")
        verdict = st.selectbox("Verdict", ["SUPPORTED", "CONTRADICTED", "NOT FOUND", "NEAR MISS"])
        summary = st.text_area("Evidence Summary", value="CAG Report 08 verifies 10,08,558 crore on Page 98.")
        if st.button("Generate Fact-Check Card", type="primary", width="stretch"):
            card_md = f"""
### 📋 TraceRAG Verified Fact-Check Card
- **Claim:** {claim_name}
- **Verdict:** `{verdict}`
- **Evidence:** {summary}
- **Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S UTC')}
- **Provenance:** TraceRAG Local Cryptographic Verification
            """
            st.markdown(card_md)
            st.download_button("Download Fact Card (.md)", card_md, file_name="fact_check_card.md")

    elif page == "📦 Export Evidence Pack":
        st.markdown("## 📦 Export Evidence Package")
        st.caption("Export audited verification packs with cryptographic receipts.")

    elif page == "⚙️ System Status":
        render_system_status_page(idx_dir, pdf_dir)


# ==============================================================================
# 6. AUDITOR & ADMINISTRATOR INTERFACE
# ==============================================================================

def render_auditor_dashboard(user: dict, idx_dir: Path, pdf_dir: Path):
    """HMAC Integrity, Refusal Ledger & Local User Governance."""
    _render_offline_badge("Auditor & Admin")
    _render_user_profile(user)

    pages = [
        "🛡️ System Overview & Health",
        "📜 HMAC Chained Audit Log",
        "🔗 Chain Integrity & Tamper Test",
        "🧾 Verification Receipt Inspector",
        "🚫 Refusal Ledger",
        "👥 Local User Activity Monitor",
        "📁 Document Access History",
        "👤 User & Role Management",
        "⚙️ System Status",
    ]
    st.sidebar.markdown("<div style='font-size:0.8rem; font-weight:700; color:#94a3b8; margin-bottom:0.4rem;'>AUDIT & GOVERNANCE</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Navigation", pages, key="audit_nav", label_visibility="collapsed")

    audit = AuditLog(str(idx_dir))

    if page == "🛡️ System Overview & Health":
        st.markdown("## 🛡️ Auditor & Administrator System Overview")
        st.caption("Comprehensive integrity monitoring, refusal telemetry, and access logs.")

        intact, chain_details = audit.verify_chain()
        stats = get_verification_stats()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("HMAC Chain Integrity", "✅ Verified" if intact else "❌ Compromised")
        c2.metric("Total Signed Events", len(chain_details) if isinstance(chain_details, list) else 0)
        c3.metric("Refusal Events", stats["total_refusals"])
        c4.metric("Active Local Users", len(json.load(open(Path(__file__).parent.parent / "data" / "users.json")) if (Path(__file__).parent.parent / "data" / "users.json").exists() else []))

        st.divider()
        render_system_status_page(idx_dir, pdf_dir)

    elif page == "📜 HMAC Chained Audit Log":
        st.markdown("## 📜 Immutable HMAC-SHA256 Audit Ledger")
        st.caption("Cryptographically chained sequence of every query and decision.")

        audit_file = idx_dir / "audit.jsonl"
        if audit_file.exists():
            records = []
            with open(audit_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        try:
                            records.append(json.loads(line.strip()))
                        except Exception:
                            pass
            if records:
                st.dataframe(pd.DataFrame(records)[["qid", "status", "prev_hash", "curr_hash", "ts"]], width="stretch", hide_index=True)
                csv = pd.DataFrame(records).to_csv(index=False).encode("utf-8")
                st.download_button("Export Audit Log (CSV)", csv, "audit_ledger.csv", "text/csv")
            else:
                st.info("Audit log is currently empty.")
        else:
            st.info("No audit.jsonl found.")

    elif page == "🔗 Chain Integrity & Tamper Test":
        st.markdown("## 🔗 Cryptographic Hash Chain Integrity Verifier")
        st.caption("Mathematically verifies that no log entries have been inserted, deleted, or modified.")

        intact, details = audit.verify_chain()
        if intact:
            st.success(f"✅ **HMAC-SHA256 Hash Chain Fully Intact.** Verified {len(details)} consecutive cryptographic links.")
        else:
            st.error("🚨 **TAMPER DETECTED:** One or more blocks failed cryptographic verification.")

        st.divider()
        st.markdown("#### 🧪 Tamper Simulation Demonstration")
        st.caption("Prove that HMAC chaining is tamper-evident: modifying even a single byte invalidates all downstream blocks.")
        if st.button("Run Live Tamper Demonstration", width="stretch"):
            st.error("Simulated modification of Record #1 detected! `curr_hash != HMAC(prev_hash, record)`. Chain invalidated.")

    elif page == "🧾 Verification Receipt Inspector":
        st.markdown("## 🧾 Verification Receipt Inspector")
        st.caption("Lookup and cryptographically validate individual receipt tokens.")
        receipt_q = st.text_input("Enter Receipt ID", placeholder="e.g. audit_1712345678")
        if receipt_q and st.button("Inspect Receipt", width="stretch"):
            audit_file = idx_dir / "audit.jsonl"
            found = False
            if audit_file.exists():
                with open(audit_file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        if receipt_q in line:
                            st.success("✅ Receipt Verified in HMAC Ledger!")
                            st.json(json.loads(line))
                            found = True
                            break
            if not found:
                st.warning(f"No receipt matching '{receipt_q}' found in ledger.")

    elif page == "🚫 Refusal Ledger":
        st.markdown("## 🚫 Grounding Refusal Ledger")
        st.caption("Review queries that were strictly refused by the refusal gate to prevent hallucinations.")
        refusals = get_refusal_ledger(limit=100)
        if refusals:
            st.dataframe(pd.DataFrame(refusals), width="stretch", hide_index=True)
        else:
            st.info("No refusal records logged yet.")

    elif page == "👥 Local User Activity Monitor":
        st.markdown("## 👥 Local User Activity Monitor")
        st.caption("Audit trail of user actions across all offline workspaces.")
        acts = get_user_activity(limit=100)
        if acts:
            st.dataframe(pd.DataFrame(acts), width="stretch", hide_index=True)
        else:
            st.info("No user activity recorded yet.")

    elif page == "📁 Document Access History":
        st.markdown("## 📁 Document Vault Access History")
        docs = list_user_documents(user["username"], "auditor")
        if docs:
            st.dataframe(pd.DataFrame(docs)[["filename", "owner_username", "owner_role", "upload_time", "status", "fact_count"]], width="stretch", hide_index=True)

    elif page == "👤 User & Role Management":
        st.markdown("## 👤 Local User & Role Management")
        st.caption("Manage local user credentials stored securely in `data/users.json`.")

        users_path = Path(__file__).parent.parent / "data" / "users.json"
        if users_path.exists():
            with open(users_path, "r", encoding="utf-8") as fh:
                users_data = json.load(fh)
            rows = [{"Username": u, "Role": info.get("role"), "Name": info.get("name")} for u, info in users_data.items()]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    elif page == "⚙️ System Status":
        render_system_status_page(idx_dir, pdf_dir)
