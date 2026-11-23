# TraceRAG — Enterprise Multimodal Evidence-Intelligence Platform

**Problem PS-03 · CIT Hackathon**  
Analysts, journalists, students and government users ask questions over long government report PDFs. Key figures live inside charts, tables, maps and scanned annexures. Every answer cites its source page. The system refuses when evidence is insufficient.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/harshax-cit/TRUSTRAG
cd TRUSTRAG

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Tesseract OCR (required for scanned PDFs)
#    macOS:  brew install tesseract
#    Ubuntu: sudo apt install tesseract-ocr

# 5. Download dataset
python3 - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download(repo_id="Tarakeshwaran/CIT_Hackathon_PS03_rag",
                  repo_type="dataset", local_dir="data/raw")
EOF

# 6. Build the index
python run.py build data/raw/pdfs

# 7. Launch (Online mode — all roles)
cp .env.online .env && export $(cat .env | xargs)
streamlit run app.py

# 8. Launch (Government offline mode)
./start_offline.sh
```

---

## Deployment Modes

### Online Mode (Analyst, Journalist, Student, Fact-Checker, Auditor)

```bash
cp .env.online .env
# Optional: add API keys for AI features
# GROQ_API_KEY=gsk_...
# YOUTUBE_API_KEY=AIza...
export $(cat .env | xargs)
streamlit run app.py
```

Open http://localhost:8501 and login with any non-government account.

### Government Offline Mode

```bash
# Requires Tesseract. Optionally: Ollama for local LLM.
./start_offline.sh
```

Login with `government` account. All processing is local — no external network calls.

**Prerequisites for Ollama (optional, conversational LLM):**
```bash
# Install Ollama: https://ollama.ai
ollama serve &
ollama pull llama3.2
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GOVERNMENT_MODE` | `false` | Set to `offline` for government air-gapped mode |
| `AI_PROVIDER` | `cloud` | `local` (Ollama) or `cloud` (Groq/Anthropic) |
| `EXTERNAL_API_ENABLED` | `true` | Set to `false` to block all external calls |
| `AUDIT_HMAC_KEY` | dev key | HMAC key for audit chain — **change before production** |
| `GROQ_API_KEY` | unset | Groq API key for AI flashcards/quiz/summary |
| `YOUTUBE_API_KEY` | unset | YouTube Data API v3 for video recommendations |
| `ANTHROPIC_API_KEY` | unset | Anthropic Claude (fallback if Groq unavailable) |
| `TRACERAG_USERS_FILE` | unset | Path to JSON file with custom user accounts |
| `MAX_UPLOAD_MB` | `50` | Max PDF upload size in MB |
| `MAX_UPLOAD_PAGES` | `300` | Max pages per uploaded PDF |
| `RETENTION_HOURS` | `24` | Hours before uploaded sessions auto-delete |

---

## User Accounts

Default accounts (change in production via `TRACERAG_USERS_FILE`):

| Username | Password | Role | Environment |
|---|---|---|---|
| `government` | `gov-secure-2024` | Government | 🔒 Offline only |
| `analyst` | `analyst-pass` | Policy Analyst | 🌐 Online |
| `journalist` | `press-pass` | Journalist | 🌐 Online |
| `student` | `learn-2024` | Student | 🌐 Online + AI |
| `checker` | `verify-pass` | Fact-Checker | 🌐 Online |
| `auditor` | `audit-admin` | Auditor/Admin | 🌐 Online (all tabs) |

Self-registration is available for: Student, Analyst, Journalist, Fact-Checker.  
Government and Auditor accounts must be provisioned by an administrator.

---

## Architecture

```
One codebase — two isolated environments
─────────────────────────────────────────────────────────────────
  LOGIN SCREEN (single page)
       │
       ├─► government role ──► 🔒 OFFLINE ENVIRONMENT
       │                            Local PDF storage
       │                            Local SQLite (data/gov_index)
       │                            Local Tesseract OCR
       │                            Local BM25 retrieval
       │                            Local HMAC audit log
       │                            NO external API calls
       │
       └─► all other roles ──► 🌐 ONLINE ENVIRONMENT
                                    Shared index (data/index)
                                    Optional: Groq AI, YouTube API
                                    Role-specific tab visibility
                                    Per-session PDF uploads
```

### Key modules

| Module | Purpose |
|---|---|
| `tracerag/ingest.py` | PDF → SQLite facts (tables, charts, OCR) |
| `tracerag/engine.py` | BM25 retrieval, fact scoring, refusal gate |
| `tracerag/verify.py` | Claim-to-pixel verification, file hash check |
| `tracerag/audit.py` | HMAC-SHA256 chain log, tamper demo |
| `tracerag/role_views.py` | Six role-specific Streamlit dashboards |
| `tracerag/system_status.py` | Offline diagnostics (Tesseract, Ollama, DB) |
| `tracerag/docstore.py` | Document registry, user activity, refusal records |
| `config.py` | Environment detection, path routing |
| `auth.py` | PBKDF2 auth, role permissions, self-registration |
| `study/ai_generate.py` | AI flashcards/quiz via Groq or Anthropic |
| `study/youtube.py` | YouTube API recommendations (blocked in gov mode) |

---

## CLI Commands

```bash
# Build index from PDFs
python run.py build data/raw/pdfs

# Answer practice questions
python run.py answer data/raw/practice_questions.jsonl --out outputs/predictions.jsonl

# Strict mode (6-field output only)
python run.py answer data/raw/practice_questions.jsonl --strict

# Verify audit chain integrity
python run.py verify-chain

# Export audit log
python run.py export-audit outputs/audit_export.jsonl
```

---

## Evaluation Results (practice set, 10 questions)

| Metric | Score |
|---|---|
| Answer accuracy | **100%** |
| Page accuracy | 60% |
| Status accuracy | 90% |
| Weighted score | **87%** |
| Refusal precision (12 synthetic) | **100%** |

---

## Regenerating the Audit Log

If the HMAC key is changed, the existing audit chain becomes invalid. Regenerate:

```bash
export AUDIT_HMAC_KEY=your-new-key
python3 - <<'EOF'
import os
for f in ["data/index/audit.jsonl", "data/index/audit_anchor.txt"]:
    if os.path.exists(f): os.remove(f)
from tracerag.audit import AuditLog
audit = AuditLog("data/index")
audit.log_event("system", {"event": "audit_reset"})
ok, msg = audit.verify_chain()
print(f"Chain: {'OK' if ok else 'BROKEN'} — {msg}")
EOF
```

---

## Security Notes

- Audit log is **tamper-evident, not tamper-proof** — an attacker with the HMAC key can re-sign
- SQL is fully parameterised — no injection paths
- PDF instruction text is treated as data, never followed
- Government mode blocks all external network calls at the config layer
- API keys are never logged or shown in the UI

---

## Tests

```bash
# All tests
python -m pytest tests/ -q

# Offline-specific tests
python -m pytest tests/test_offline_full.py -v

# Role-based routing tests
python -m pytest tests/test_roles.py -v

# Security tests
python -m pytest tests/test_regressions.py -v
```

---

## Limitations

- CPI conflict (q775331): `status=answer` instead of `status=conflict` — planted 5.6% value has `period=None`
- Page accuracy 60%: refusals have no page (expected); two_doc question returns same page for both
- Chart OCR year pairing may fail if x-axis labels are garbled
- Government Ollama LLM is optional — without it, extractive summaries are used
- Real YouTube API and Anthropic Claude require funded accounts
