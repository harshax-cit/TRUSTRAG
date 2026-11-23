"""
tracerag/docstore.py – Persistent Document Ownership and Access Control Registry.

Enforces:
  - Document ownership by username and role
  - Private document isolation (users only see/access their own files)
  - Separate storage for Government (data/gov_index/docstore.db) vs Online (data/index/docstore.db)
  - Multi-file status tracking (uploading, processing, indexed, error)
  - Metadata indexing for PDF, images, tabular files (CSV/Excel), and media (video)
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DOCSTORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_documents (
    doc_id          TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    owner_username  TEXT NOT NULL,
    owner_role      TEXT NOT NULL,
    upload_time     TEXT NOT NULL,
    status          TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    index_path      TEXT NOT NULL,
    fact_count      INTEGER DEFAULT 0,
    page_count      INTEGER DEFAULT 0,
    error_message   TEXT,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_owner ON user_documents(owner_username);
CREATE INDEX IF NOT EXISTS idx_doc_role ON user_documents(owner_role);
CREATE INDEX IF NOT EXISTS idx_doc_sha ON user_documents(sha256);

CREATE TABLE IF NOT EXISTS user_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    timestamp TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS refusal_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT,
    question TEXT NOT NULL,
    username TEXT,
    role TEXT,
    reason TEXT,
    timestamp TEXT NOT NULL
);
"""


def get_docstore_path(is_government: bool = False) -> str:
    """Return the isolated docstore db path based on government status."""
    root = Path(__file__).parent.parent
    if is_government:
        base = root / "data" / "gov_index"
    else:
        base = root / "data" / "index"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "docstore.db")


def init_docstore(db_path: str) -> None:
    """Initialize the SQLite schema for document storage."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        conn.executescript(DOCSTORE_SCHEMA)
        conn.commit()


def register_document(
    filename: str,
    file_type: str,
    file_bytes: bytes,
    owner_username: str,
    owner_role: str,
    is_government: bool = False,
    metadata: Optional[dict] = None,
) -> dict:
    """
    Save uploaded file bytes to user-scoped directory and register in docstore.
    Enforces user isolation and SHA-256 calculation.
    """
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)

    doc_id = uuid.uuid4().hex
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
    file_size = len(file_bytes)
    upload_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    root = Path(__file__).parent.parent
    storage_base = root / "data" / ("gov_docs" if is_government else "user_docs")
    user_storage = storage_base / owner_username
    user_storage.mkdir(parents=True, exist_ok=True)

    dest_file = user_storage / f"{doc_id}_{filename}"
    dest_file.write_bytes(file_bytes)

    # Index path for document-specific extracted facts
    doc_index_dir = user_storage / f"{doc_id}_index"
    doc_index_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "doc_id": doc_id,
        "filename": filename,
        "file_type": file_type.lower(),
        "file_size": file_size,
        "sha256": sha256_hash,
        "owner_username": owner_username.lower().strip(),
        "owner_role": owner_role.lower().strip(),
        "upload_time": upload_time,
        "status": "ready",
        "file_path": str(dest_file),
        "index_path": str(doc_index_dir),
        "fact_count": 0,
        "page_count": 1,
        "error_message": "",
        "metadata_json": json.dumps(metadata or {}),
    }

    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_documents (
                doc_id, filename, file_type, file_size, sha256,
                owner_username, owner_role, upload_time, status,
                file_path, index_path, fact_count, page_count,
                error_message, metadata_json
            ) VALUES (
                :doc_id, :filename, :file_type, :file_size, :sha256,
                :owner_username, :owner_role, :upload_time, :status,
                :file_path, :index_path, :fact_count, :page_count,
                :error_message, :metadata_json
            )
            """,
            record,
        )
        conn.commit()

    return record


def list_user_documents(
    owner_username: str,
    owner_role: str,
    is_government: bool = False,
    search_query: str = "",
) -> list[dict]:
    """
    List documents owned by the specified user.
    Backend access control:
      - Normal users only see their own documents.
      - Government users only see their own government documents.
      - Auditor in online mode can view all online user documents for compliance auditing.
    """
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)

    owner_username = owner_username.lower().strip()
    owner_role = owner_role.lower().strip()

    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if owner_role == "auditor" and not is_government:
            # Auditor can inspect online documents for compliance
            if search_query:
                cur.execute(
                    "SELECT * FROM user_documents WHERE filename LIKE ? ORDER BY upload_time DESC",
                    (f"%{search_query}%",),
                )
            else:
                cur.execute("SELECT * FROM user_documents ORDER BY upload_time DESC")
        else:
            # Strict ownership: only see own files
            if search_query:
                cur.execute(
                    """
                    SELECT * FROM user_documents 
                    WHERE owner_username = ? AND filename LIKE ? 
                    ORDER BY upload_time DESC
                    """,
                    (owner_username, f"%{search_query}%"),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM user_documents 
                    WHERE owner_username = ? 
                    ORDER BY upload_time DESC
                    """,
                    (owner_username,),
                )

        rows = cur.fetchall()
        return [dict(row) for row in rows]


def get_document(
    doc_id: str,
    owner_username: str,
    owner_role: str,
    is_government: bool = False,
) -> Optional[dict]:
    """Get a specific document record if authorized."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)

    owner_username = owner_username.lower().strip()
    owner_role = owner_role.lower().strip()

    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_documents WHERE doc_id = ?", (doc_id,))
        row = cur.fetchone()
        if not row:
            return None
        doc = dict(row)

        # Authorization check
        if owner_role == "auditor" and not is_government:
            return doc
        if doc["owner_username"] == owner_username:
            return doc
        return None


def update_document_status(
    doc_id: str,
    status: str,
    is_government: bool = False,
    fact_count: int = 0,
    page_count: int = 0,
    error_message: str = "",
) -> None:
    """Update ingestion/processing status."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)

    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE user_documents
            SET status = ?, fact_count = ?, page_count = ?, error_message = ?
            WHERE doc_id = ?
            """,
            (status, fact_count, page_count, error_message, doc_id),
        )
        conn.commit()


def delete_document(
    doc_id: str,
    owner_username: str,
    owner_role: str,
    is_government: bool = False,
) -> bool:
    """
    Delete a document file and registry entry if owned by user.
    """
    doc = get_document(doc_id, owner_username, owner_role, is_government)
    if not doc:
        return False

    # Remove files
    file_path = Path(doc["file_path"])
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception as e:
            logger.warning(f"Could not remove file {file_path}: {e}")

    index_path = Path(doc["index_path"])
    if index_path.exists():
        try:
            shutil.rmtree(index_path)
        except Exception as e:
            logger.warning(f"Could not remove index dir {index_path}: {e}")

    db_path = get_docstore_path(is_government)
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_documents WHERE doc_id = ?", (doc_id,))
        conn.commit()

    return True


def log_user_activity(
    username: str,
    role: str,
    action: str,
    target: str = "",
    details: str = "",
    is_government: bool = False,
) -> None:
    """Log an offline user activity event to SQLite."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO user_activity (username, role, action, target, timestamp, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username.strip(), role.strip(), action.strip(), target.strip(), now, details.strip()),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not log user activity: {e}")


def get_user_activity(is_government: bool = False, limit: int = 100) -> list[dict]:
    """Retrieve recent user activity log."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_activity ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Could not fetch user activity: {e}")
        return []


def record_refusal(
    question_id: str,
    question: str,
    username: str,
    role: str,
    reason: str,
    is_government: bool = False,
) -> None:
    """Record an ungrounded query refusal into the Refusal Ledger."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO refusal_records (question_id, question, username, role, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (question_id, question, username, role, reason, now),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not record refusal: {e}")


def get_refusal_ledger(is_government: bool = False, limit: int = 100) -> list[dict]:
    """Retrieve the Refusal Ledger for auditor and analyst review."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM refusal_records ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Could not fetch refusal ledger: {e}")
        return []


def get_verification_stats(is_government: bool = False) -> dict:
    """Compute statistics on documents, activities, and refusals."""
    db_path = get_docstore_path(is_government)
    init_docstore(db_path)
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM user_documents")
            total_docs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM user_documents WHERE status = 'ready'")
            ready_docs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM user_activity")
            total_activities = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM refusal_records")
            total_refusals = cur.fetchone()[0]
            return {
                "total_docs": total_docs,
                "ready_docs": ready_docs,
                "total_activities": total_activities,
                "total_refusals": total_refusals,
            }
    except Exception:
        return {"total_docs": 0, "ready_docs": 0, "total_activities": 0, "total_refusals": 0}

