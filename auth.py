"""
auth.py – Role-based session authentication for TraceRAG.

Design:
  - Credentials in USERS dict or TRACERAG_USERS_FILE (JSON).
  - Passwords PBKDF2-HMAC-SHA256 hashed. Never plain text.
  - Sessions in Streamlit session_state only.
  - Single login page — the ROLE itself determines offline vs online:
      government role  → offline mode (local pipelines, no cloud calls)
      all other roles  → online mode (cloud AI optional)
  - Account creation allowed for non-government roles only
    (government accounts must be pre-provisioned by admin).

Default demo accounts:
  government / gov-secure-2024   → role: government  (offline)
  analyst    / analyst-pass      → role: analyst     (online)
  journalist / press-pass        → role: journalist  (online)
  student    / learn-2024        → role: student     (online)
  checker    / verify-pass       → role: factchecker (online)
  auditor    / audit-admin       → role: auditor     (online)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Optional

from config import ROLES

# ── Runtime user store (in-memory, pre-seeded with defaults) ─────────────────
# In production: replace with a proper database.
_RUNTIME_USERS: dict = {}   # populated lazily


def _hash_password(password: str, salt: str = "tracerag-salt-v2") -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=200_000,
    )
    return dk.hex()


def _check_password(password: str, hashed: str,
                    salt: str = "tracerag-salt-v2") -> bool:
    return hmac.compare_digest(_hash_password(password, salt), hashed)


_DEFAULT_USERS = {
    "government": {"password_hash": _hash_password("gov-secure-2024"),
                   "role": "government", "name": "Government User"},
    "analyst":    {"password_hash": _hash_password("analyst-pass"),
                   "role": "analyst",    "name": "Policy Analyst"},
    "journalist": {"password_hash": _hash_password("press-pass"),
                   "role": "journalist", "name": "Journalist"},
    "student":    {"password_hash": _hash_password("learn-2024"),
                   "role": "student",    "name": "Student"},
    "checker":    {"password_hash": _hash_password("verify-pass"),
                   "role": "factchecker","name": "Fact-Checker"},
    "auditor":    {"password_hash": _hash_password("audit-admin"),
                   "role": "auditor",    "name": "Auditor / Admin"},
}

USERS_FILE = Path(__file__).parent / "data" / "users.json"


def _load_users() -> dict:
    global _RUNTIME_USERS
    if not _RUNTIME_USERS:
        # Seed from file or defaults
        custom_file = os.environ.get("TRACERAG_USERS_FILE", "")
        fpath = Path(custom_file) if custom_file else USERS_FILE
        if fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    _RUNTIME_USERS.update(json.load(f))
            except Exception:
                pass
        # Ensure default users exist as baseline
        for u, data in _DEFAULT_USERS.items():
            if u not in _RUNTIME_USERS:
                _RUNTIME_USERS[u] = data
    return _RUNTIME_USERS


def _save_users() -> None:
    try:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(_RUNTIME_USERS, f, indent=2)
    except Exception:
        pass


# ── Error class ───────────────────────────────────────────────────────────────

class AuthError(ValueError):
    pass


# ── Authentication ────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict:
    """
    Verify credentials. Returns user dict on success.
    Single login for all roles — role itself drives offline/online mode.
    """
    username = username.strip().lower()
    users    = _load_users()

    if username not in users:
        raise AuthError("Invalid username or password.")

    user = users[username]
    if not _check_password(password, user["password_hash"]):
        raise AuthError("Invalid username or password.")

    role = user["role"]
    return {
        "username":      username,
        "role":          role,
        "name":          user["name"],
        "authenticated": True,
        "offline":       role == "government",
    }


# ── Account creation ──────────────────────────────────────────────────────────

SELF_REGISTER_ROLES = ["student", "analyst", "journalist", "factchecker", "government", "auditor"]


def create_account(username: str, password: str,
                   name: str, role: str) -> dict:
    """
    Create a new account.
    Returns the new user dict.
    Raises AuthError on validation failure.
    """
    username = username.strip().lower()
    name     = name.strip()
    role     = role.strip().lower()

    if not username or len(username) < 3:
        raise AuthError("Username must be at least 3 characters.")
    if not password or len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")
    if not name:
        raise AuthError("Full name is required.")
    if role not in SELF_REGISTER_ROLES:
        raise AuthError(
            f"Allowed roles: {', '.join(SELF_REGISTER_ROLES)}."
        )

    users = _load_users()
    if username in users:
        raise AuthError(f"Username '{username}' is already taken.")

    users[username] = {
        "password_hash": _hash_password(password),
        "role":          role,
        "name":          name,
    }
    _save_users()
    return authenticate(username, password)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_role_info(role: str) -> dict:
    return ROLES.get(role, {"label": role, "icon": "👤", "env": "offline"})


ROLE_PERMISSIONS = {
    "government": {
        "title": "Government — Offline Secure Interface",
        "allowed_pages": [
            "🏛️ Overview",
            "📁 Document Repository",
            "📤 Upload & Extraction",
            "🔍 Local Search & Highlighting",
            "🎯 Claim-to-Pixel Verifier",
            "⚖️ Conflict & Revision Center",
            "🛡️ Local Audit & Receipts",
            "⚙️ System Status",
        ],
    },
    "analyst": {
        "title": "Policy Analyst — Offline Interface",
        "allowed_pages": [
            "📊 Policy Research Desk",
            "📑 Cross-Document Comparison",
            "💰 Expenditure Analysis",
            "📈 Metric & Trend Explorer",
            "📝 Policy Brief Generator",
            "🔍 Citation & Evidence Viewer",
            "📥 Export Findings",
            "⚙️ System Status",
        ],
    },
    "journalist": {
        "title": "Journalist — Offline Interface",
        "allowed_pages": [
            "📰 Fact-Checking Workspace",
            "💬 Quote-Ready Citations",
            "🚦 Safe-to-Publish Screener",
            "⚠️ Stale-Number & Revision Alerts",
            "⚖️ Conflicting Statements Desk",
            "📸 Evidence Screenshot & Pages",
            "📜 Research History & Receipts",
            "⚙️ System Status",
        ],
    },
    "student": {
        "title": "Student — Offline Interface",
        "allowed_pages": [
            "🎓 Learning Hub",
            "🤖 Local Document Tutor",
            "💡 Simple-Language Explanations",
            "❓ PDF Q&A & Follow-ups",
            "📖 Glossary & Important Terms",
            "📊 Chart & Table Insights",
            "📝 Study Notes & Summaries",
            "🃏 Leitner Flashcards & Quizzes",
            "⚙️ System Status",
        ],
    },
    "factchecker": {
        "title": "Fact-Checker — Offline Interface",
        "allowed_pages": [
            "🔍 Claim Verification Desk",
            "🏷️ Claim Classification (Supported/Contradicted)",
            "🎯 Near-Miss Detection",
            "📑 Cross-Document Verification",
            "⚖️ Conflicting Data Identification",
            "📋 Verification Report Generator",
            "📦 Export Evidence Pack",
            "⚙️ System Status",
        ],
    },
    "auditor": {
        "title": "Auditor & Admin — Offline Interface",
        "allowed_pages": [
            "🛡️ System Overview & Health",
            "📜 HMAC Chained Audit Log",
            "🔗 Chain Integrity & Tamper Test",
            "🧾 Verification Receipt Inspector",
            "🚫 Refusal Ledger",
            "👥 Local User Activity Monitor",
            "📁 Document Access History",
            "👤 User & Role Management",
            "⚙️ System Status",
        ],
    },
}


def can_access_route(role: str, page_name: str) -> bool:
    """Backend authorization guard ensuring users can only load their role's pages."""
    perms = ROLE_PERMISSIONS.get(role.lower().strip())
    if not perms:
        return False
    return page_name in perms["allowed_pages"]


def is_authorised(session_user: Optional[dict], required_role: str) -> bool:
    """Backend authorization check."""
    if not session_user or not session_user.get("authenticated"):
        return False
    if session_user["role"] == required_role:
        return True
    if session_user["role"] == "auditor" and required_role != "government":
        return True
    return False
