# TraceRAG — Multimodal RAG with Explainability

**Problem PS-03 · CIT Hackathon**

Analysts, journalists and students ask questions over a collection of government report PDFs.
Key figures sit inside charts, tables, maps and scanned annexures.
Every answer cites its source document and page. When the collection does not contain the answer
the system refuses instead of guessing.

---

## Quick start

```bash
# 1. Clone and create environment
git clone <repo-url>
cd tracerag
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Download dataset (requires huggingface_hub)
python3 - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="Tarakeshwaran/CIT_Hackathon_PS03_rag",
    repo_type="dataset",
    local_dir="data/raw"
)
EOF

# 3. Build the index
python run.py build data/raw/pdfs

# 4. Answer the practice questions
python run.py answer data/raw/practice_questions.jsonl --out outputs/predictions.jsonl

# 5. Strict mode (6-field output only)
python run.py answer data/raw/practice_questions.jsonl --strict --out outputs/predictions.strict.jsonl

# 6. Launch the UI
streamlit run app.py
```

---

## Commands

| Command | Description |
|---|---|
| `python run.py build <pdf_dir>` | Ingest PDFs, build SQLite fact DB and BM25 index |
| `python run.py answer <questions.jsonl> [--strict]` | Answer questions, write predictions.jsonl |
| `python run.py verify-chain` | Verify audit log HMAC chain integrity |
| `python run.py export-audit <out.jsonl>` | Export audit log |
| `streamlit run app.py` | Launch 5-lens UI |

---

## Output format

Every answer is one JSON record:

```json
{
  "id": "q123",
  "answer": "5.4 per cent",
  "doc": "es2023-24_money_prices.pdf",
  "page": 49,
  "bbox": [60, 100, 400, 120],
  "status": "answer"
}
```

`status` is one of `answer | conflict | refuse`.

Extended mode adds `evidence`, `confidence`, `reason_codes`, `audit_receipt`.

---

## Architecture

```
run.py          CLI entry point
app.py          Streamlit UI (5 lenses)
eval.py         Evaluation against practice answers
tracerag/
  textutil.py   Period / unit / qualifier normalisation, stemming, IDF
  ingest.py     PDF → facts DB (tables, charts, scanned OCR)
  retrieve.py   BM25 retrieval + RRF fusion
  engine.py     Query classification, fact scoring, refusal gate, conflict detection
  verify.py     Claim-to-pixel verification, file hash check
  audit.py      HMAC-SHA256 chain log, tamper demo
  highlight.py  PDF page renderer with bbox highlight
  llm.py        Optional LLM hook (disabled without API key)
tests/
  test_regressions.py   38 unit + security tests
  test_app.py           7 Streamlit AppTest smoke tests
```

---

## Evaluation results (practice set, 10 questions)

| Metric | Score |
|---|---|
| Answer accuracy | 100% |
| Page accuracy | 60% |
| Status accuracy | 90% |
| **Weighted score** | **87%** |

---

## Security

- Edited log row detected via HMAC chain
- Truncated log caught via anchor file
- Log rewritten without key detected
- Modified PDF → refuse (hash mismatch)
- SQL parameterised throughout (no injection path)
- Instruction text in PDFs treated as data, never followed
- No secrets in repo — set `AUDIT_HMAC_KEY` env var in production

---

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `AUDIT_HMAC_KEY` | HMAC key for audit chain | `tracerag-default-dev-key-change-in-prod` |
| `OPENAI_API_KEY` | Enable GPT-4o chart reading | unset (offline mode) |
| `ANTHROPIC_API_KEY` | Enable Claude chart reading | unset (offline mode) |

---

## Limitations

- CPI conflict question (q775331): answer value is correct (5.4%) but `status=answer` instead of `status=conflict`. The planted 5.6% value in the ORGANIZER-MODIFIED file has `period=None`, which the conflict detector does not currently match against.
- Page accuracy is 60%: refusal questions have no page (expected), and two_doc question returns both pages as the same document.
- Chart data labels are extracted by OCR + spatial x-axis pairing. If chart x-axis labels are garbled by OCR, year pairing may fail.
- Scanned page OCR quality depends on scan resolution. Low-confidence facts carry a warning in the Student lens.
- No cross-document arithmetic (computing differences across two separate PDFs).
- LLM/vision model integration is a stub; outputs are always re-verified before use.

---

## Requirements

See `requirements.txt`. Core dependencies:

- Python 3.12+
- PyMuPDF (pymupdf)
- pytesseract + Tesseract 5.x
- rank-bm25
- streamlit
- pandas
- pillow
- huggingface-hub
