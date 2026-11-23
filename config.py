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
    Returns True when GOVERNMENT_MODE=offline.
    Any other value (including unset) means online mode.
    """
    return os.environ.get("GOVERNMENT_MODE", "").strip().lower() == "offline"


def ai_provider() -> str:
    """
    Returns 'local' or 'cloud'.
    In government mode always returns 'local' regardless of env var.
    """
    if is_government_mode():
        return "local"
    return os.environ.get("AI_PROVIDER", "cloud").strip().lower()


def external_api_enabled() -> bool:
    """
    Returns False in government mode (enforced), or based on env var online.
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
    if is_government_mode():
        return "🔒 OFFLINE — Government Secure Environment"
    return "🌐 ONLINE"


def get_ai_label() -> str:
    if is_government_mode():
        return "🖥️ Local AI (offline)"
    if os.environ.get("OPENAI_API_KEY"):
        return "☁️ OpenAI (cloud)"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "☁️ Anthropic (cloud)"
    return "💻 Extractive (no key set)"


# ── Role definitions ──────────────────────────────────────────────────────────

ROLES = {
    "government":    {"env": "offline", "label": "Government",          "icon": "🏛️"},
    "analyst":       {"env": "online",  "label": "Policy Analyst",      "icon": "📊"},
    "journalist":    {"env": "online",  "label": "Journalist",          "icon": "📰"},
    "student":       {"env": "online",  "label": "Student",             "icon": "🎓"},
    "factchecker":   {"env": "online",  "label": "Fact-Checker",        "icon": "🔍"},
    "auditor":       {"env": "online",  "label": "Auditor / Admin",     "icon": "🔐"},
}

# Tabs each role can see
ROLE_TABS = {
    "government": ["📊 Analyst", "🔍 Fact-checker", "🔐 Auditor"],
    "analyst":    ["📊 Analyst", "📰 Journalist", "🔍 Fact-checker", "🔐 Auditor"],
    "journalist": ["📰 Journalist", "🔍 Fact-checker"],
    "student":    ["🎓 Student", "📤 Upload", "📝 Summary",
                   "🃏 Flashcards", "🧠 Quiz", "▶️ Videos", "❓ Ask", "📈 Progress"],
    "factchecker":["🔍 Fact-checker", "📊 Analyst"],
    "auditor":    ["🔐 Auditor", "📊 Analyst", "📰 Journalist",
                   "🔍 Fact-checker", "🎓 Student"],
}
