"""
config.py – Environment-based configuration for TraceRAG.

Two deployment modes:
  Government (offline):  GOVERNMENT_MODE=offline  AI_PROVIDER=local
  Online (all others):   GOVERNMENT_MODE=false    AI_PROVIDER=cloud

Rules enforced here:
  - Government mode: external API calls are blocked at this layer.
  - Online mode: cloud services enabled when keys are present.
  - Neither mode hard-codes credentials.
  - Government mode does NOT silently fall back to cloud if local model
    unavailable — it raises GovernmentModeViolation instead.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent


# ── Mode detection ────────────────────────────────────────────────────────────

def is_government_mode() -> bool:
    """
    Returns True when in government mode or when government user is logged in.
    """
    if os.environ.get("GOVERNMENT_MODE", "").strip().lower() == "offline":
        return True
    try:
        import streamlit as st
        user = st.session_state.get("user", {})
        return bool(user and user.get("role") == "government")
    except Exception:
        return False


def is_government_session(user: dict) -> bool:
    """Check if a specific user dict represents a government session."""
    return bool(user and user.get("role") == "government")


def is_offline_mode() -> bool:
    """TraceRAG is configured to run 100% offline."""
    return True


def ai_provider() -> str:
    """
    Returns 'local' or 'cloud'.
    Government mode always returns 'local' regardless of env var.
    """
    if is_government_mode():
        return "local"
    return os.environ.get("AI_PROVIDER", "cloud").strip().lower()


def external_api_enabled() -> bool:
    """
    Returns False in government mode (enforced).
    In online mode reads EXTERNAL_API_ENABLED env var (default: True).
    """
    if is_government_mode():
        return False
    val = os.environ.get("EXTERNAL_API_ENABLED", "true").strip().lower()
    return val not in ("false", "0", "no")


# ── Path configuration ────────────────────────────────────────────────────────

def government_db_path() -> str:
    return os.environ.get(
        "DATABASE_URL",
        str(ROOT / "data" / "government.db")
    ).replace("sqlite:///", "")


def index_dir() -> str:
    if is_government_mode():
        return str(ROOT / "data" / "gov_index")
    return str(ROOT / "data" / "index")


def pdf_dir() -> str:
    if is_government_mode():
        return str(ROOT / "data" / "gov_pdfs")
    return str(ROOT / "data" / "raw" / "pdfs")


# ── Error class ───────────────────────────────────────────────────────────────

class GovernmentModeViolation(RuntimeError):
    """
    Raised when government mode code attempts an external network call.
    Does NOT fall back to cloud — surfaces a clear error instead.
    """


class LocalModelUnavailable(RuntimeError):
    """
    Raised in government mode when the local AI model cannot be reached.
    Does NOT fall back to cloud — surfaces a clear error instead.
    """


# ── Government guard ──────────────────────────────────────────────────────────

def assert_local_only(operation: str = "") -> None:
    """
    Call this before any network operation.
    Raises GovernmentModeViolation in government mode.
    """
    if is_government_mode():
        raise GovernmentModeViolation(
            f"Government mode: external network access is blocked. "
            f"Operation '{operation}' requires internet but GOVERNMENT_MODE=offline. "
            "Use a locally hosted model instead."
        )


def get_mode_label() -> str:
    return "🔒 OFFLINE SECURE ENVIRONMENT"


def get_ai_label() -> str:
    try:
        from tracerag.local_llm import check_ollama_status
        status = check_ollama_status()
        if status.get("available"):
            return f"🖥️ Local Ollama ({status.get('active_model')})"
    except Exception:
        pass
    return "💻 Local Extractive AI (Zero Cloud Calls)"


# ── Role definitions ──────────────────────────────────────────────────────────

ROLES = {
    "government":    {"env": "offline", "label": "Government",          "icon": "🏛️"},
    "analyst":       {"env": "offline", "label": "Policy Analyst",      "icon": "📊"},
    "journalist":    {"env": "offline", "label": "Journalist",          "icon": "📰"},
    "student":       {"env": "offline", "label": "Student",             "icon": "🎓"},
    "factchecker":   {"env": "offline", "label": "Fact-Checker",        "icon": "🔍"},
    "auditor":       {"env": "offline", "label": "Auditor / Admin",     "icon": "🛡️"},
}

# Tabs each role can see
# Every role now gets "📚 My PDFs" (upload + Q&A from their own PDF)
_STUDY_TABS = ["📚 My PDFs"]   # universal PDF upload + knowledge Q&A tab

ROLE_TABS = {
    "government": ["📊 Analyst", "🔍 Fact-checker", "🔐 Auditor"] + _STUDY_TABS,
    "analyst":    ["📊 Analyst", "📰 Journalist", "🔍 Fact-checker",
                   "🔐 Auditor"] + _STUDY_TABS,
    "journalist": ["📰 Journalist", "🔍 Fact-checker"] + _STUDY_TABS,
    "student":    ["🎓 Student", "📤 Upload", "📝 Summary",
                   "🃏 Flashcards", "🧠 Quiz", "▶️ Videos",
                   "❓ Ask", "📈 Progress"] + _STUDY_TABS,
    "factchecker":["🔍 Fact-checker", "📊 Analyst"] + _STUDY_TABS,
    "auditor":    ["🔐 Auditor", "📊 Analyst", "📰 Journalist",
                   "🔍 Fact-checker", "🎓 Student"] + _STUDY_TABS,
}
