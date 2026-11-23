#!/usr/bin/env bash
# ==============================================================================
# TraceRAG — Government Offline Secure Launcher
# Usage:
#   ./start_offline.sh           # Start in offline mode (Ollama optional)
#   ./start_offline.sh --strict  # Exit with error if Ollama is not running
# ==============================================================================
set -e

STRICT=false
for arg in "$@"; do
  [[ "$arg" == "--strict" ]] && STRICT=true
done

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "============================================================"
echo "🌿 TraceRAG — Government Offline Secure Environment"
echo "============================================================"

# ── 1. Enforce offline environment flags ──────────────────────────────────────
export GOVERNMENT_MODE=offline
export AI_PROVIDER=local
export EXTERNAL_API_ENABLED=false
export PYTHONPATH="$DIR:$PYTHONPATH"
# Load additional env vars from .env.government if present
if [ -f ".env.government" ]; then
    set -o allexport
    source .env.government
    set +o allexport
    echo "✔ Loaded .env.government"
fi

# ── 2. Virtual environment ────────────────────────────────────────────────────
if [ -d ".venv" ]; then
    echo "✔ Activating .venv..."
    source .venv/bin/activate
else
    echo "⚠  No .venv found. Using system Python."
fi

# ── 3. Python dependencies check ─────────────────────────────────────────────
echo "✔ Checking Python dependencies..."
python3 -c "import streamlit, pymupdf, pytesseract, rank_bm25, pandas, fpdf" 2>/dev/null \
  || { echo "❌ Missing Python dependencies. Run: pip install -r requirements.txt"; exit 1; }

# ── 4. Tesseract OCR (required) ───────────────────────────────────────────────
if command -v tesseract >/dev/null 2>&1; then
    echo "✔ Tesseract OCR: $(tesseract --version 2>&1 | head -n 1)"
else
    echo "❌ Tesseract OCR not found on PATH."
    echo "   macOS:  brew install tesseract"
    echo "   Ubuntu: sudo apt install tesseract-ocr"
    exit 1
fi

# ── 5. Index check ────────────────────────────────────────────────────────────
INDEX_DB="$DIR/data/gov_index/facts.db"
if [ ! -f "$INDEX_DB" ]; then
    echo "⚠  Government index not found at $INDEX_DB"
    echo "   Run first: python run.py build data/gov_pdfs --index-dir data/gov_index"
    echo "   (Continuing — you can build the index from the UI)"
fi

# ── 6. Ollama local LLM (optional) ───────────────────────────────────────────
if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✔ Ollama daemon running at http://localhost:11434"
    # Check if a usable model is available
    MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "
import sys,json
d=json.load(sys.stdin)
names=[m['name'] for m in d.get('models',[])]
print(' '.join(names[:3]) if names else 'none')
" 2>/dev/null || echo "unknown")
    echo "  Available models: $MODELS"
else
    if [ "$STRICT" = true ]; then
        echo "❌ Ollama daemon is NOT running (--strict mode requires it)."
        echo "   Start it with: ollama serve"
        echo "   Then pull a model: ollama pull llama3.2"
        exit 1
    else
        echo "ℹ  Ollama not running — AI features will use extractive mode."
        echo "   To enable local LLM: ollama serve && ollama pull llama3.2"
    fi
fi

# ── 7. Audit chain check ──────────────────────────────────────────────────────
echo "✔ Verifying audit chain..."
python3 - <<'PYEOF' 2>/dev/null || echo "  (Audit chain will be initialised on first run)"
from tracerag.audit import AuditLog
import os
idx = os.path.join(os.environ.get("DIR", "."), "data", "gov_index")
if os.path.exists(os.path.join(idx, "audit.jsonl")):
    ok, msg = AuditLog(idx).verify_chain()
    print(f"  {'✅' if ok else '❌'} {msg}")
PYEOF

echo "------------------------------------------------------------"
echo "🚀 Starting TraceRAG (Government Offline Mode)..."
echo "   URL: http://localhost:8501"
echo "   Login: government / gov-secure-2024"
echo "------------------------------------------------------------"

exec .venv/bin/streamlit run app.py \
    --server.headless=true \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --server.fileWatcherType=none
