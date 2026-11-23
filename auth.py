"""
auth.py – Role-based session authentication for TraceRAG.

Design:
  - Credentials stored in USERS dict or loaded from TRACERAG_USERS_FILE (JSON).
  - Passwords are bcrypt-hashed. Never stored in plain text.
  - Sessions stored in Streamlit session_state only (no external session DB needed).
  - Government role is only allowed when GOVERNMENT_MODE=offline.
  - Online roles are only allowed when GOVERNMENT_MODE != offline.
  - Backend enforces role constraints; frontend merely shows the right tabs.

Default demo accounts (change before production):
  government / gov-secure-2024   → role: government
  analyst    / analyst-pass      → role: analyst
  journalist / press-pass        → role: journalist
  student    / learn-2024        → role: student
  checker    / verify-pass       → role: factchecker
  auditor    / audit-admin       → role: auditor

Set TRACERAG_USERS_FILE=/path/to/users.json to override defaults.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Optional

from config import is_government_mode, ROLES


# ── Password hashing (PBKDF2-HMAC-SHA256, no external deps) ──────────────────

def _hash_password(password: str, salt: str = "tracerag-salt") -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=200_000,
    )
    return dk.hex()


def _check_password(password: str, hashed: str, salt: str = "tracerag-salt") -> bool:
    return hmac.compare_digest(
        _hash_password(password, salt), hashed
    )


# ── Default user store ────────────────────────────────────────────────────────

_DEFAULT_USERS = {
    "government": {
        "password_hash": _hash_password("gov-secure-2024"),
        "role": "government",
        "name": "Government User",
    },
    "analyst": {
        "password_hash": _hash_password("analyst-pass"),
        "role": "analyst",
        "name": "Policy Analyst",
    },
    "journalist": {
        "password_hash": _hash_password("press-pass"),
        "role": "journalist",
        "name": "Journalist",
    },
    "student": {
        "password_hash": _hash_password("learn-2024"),
        "role": "student",
        "name": "Student",
    },
    "checker": {
        "password_hash": _hash_password("verify-pass"),
        "role": "factchecker",
        "name": "Fact-Checker",
    },
    "auditor": {
        "password_hash": _hash_password("audit-admin"),
        "role": "auditor",
        "name": "Auditor / Admin",
    },
}


def _load_users() -> dict:
    users_file = os.environ.get("TRACERAG_USERS_FILE", "")
    if users_file and Path(users_file).exists():
        with open(users_file) as f:
            return json.load(f)
    return _DEFAULT_USERS


# ── Authentication ────────────────────────────────────────────────────────────

class AuthError(ValueError):
    """Raised when login or authorization fails."""


def authenticate(username: str, password: str) -> dict:
    """
    Verify credentials. Returns user dict on success.
    Raises AuthError on failure.
    Backend enforces environment constraints:
      - 'government' role only allowed in GOVERNMENT_MODE=offline.
      - All other roles only allowed when NOT in government mode.
    """
    username = username.strip().lower()
    users    = _load_users()

    if username not in users:
        raise AuthError("Invalid username or password.")

    user = users[username]
    if not _check_password(password, user["password_hash"]):
        raise AuthError("Invalid username or password.")

    role = user["role"]

    # ── Backend enforcement: environment vs role ──────────────────────────────
    if role == "government" and not is_government_mode():
        raise AuthError(
            "Government accounts require GOVERNMENT_MODE=offline. "
            "This instance is running in online mode."
        )

    if role != "government" and is_government_mode():
        raise AuthError(
            "This instance runs in Government offline mode. "
            "Only government accounts are permitted here."
        )

    return {
        "username": username,
        "role":     role,
        "name":     user["name"],
        "authenticated": True,
    }


def get_role_info(role: str) -> dict:
    return ROLES.get(role, {"label": role, "icon": "👤", "env": "online"})


def is_authorised(session_user: Optional[dict], required_role: str) -> bool:
    """
    Backend authorization check.
    Use this before serving any role-specific content.
    """
    if not session_user or not session_user.get("authenticated"):
        return False
    if session_user["role"] == required_role:
        return True
    # Auditor can access everything online
    if session_user["role"] == "auditor" and required_role != "government":
        return True
    return False
