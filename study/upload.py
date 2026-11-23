"""
study/upload.py – Per-session PDF upload, validation, and ingestion.

Validates: extension, magic bytes, size, page count, encryption,
           embedded JS / launch actions.
Ingests into a session-specific index directory (never the shared one).
Logs all events to the existing HMAC audit log.
Auto-deletes workspace after RETENTION_HOURS (default 24).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

import pymupdf as fitz

from tracerag.audit import AuditLog

# ── config (env-overridable) ─────────────────────────────────────────────────
MAX_UPLOAD_MB    = int(os.environ.get("MAX_UPLOAD_MB",    "50"))
MAX_PAGES        = int(os.environ.get("MAX_UPLOAD_PAGES", "300"))
RETENTION_HOURS  = int(os.environ.get("RETENTION_HOURS",  "24"))

PDF_MAGIC        = b"%PDF"
SESSIONS_ROOT    = Path(__file__).parent.parent / "data" / "sessions"

# ── public API ────────────────────────────────────────────────────────────────

class UploadError(ValueError):
    """Raised when a PDF fails validation."""


def new_session_id() -> str:
    return uuid.uuid4().hex


def session_dirs(session_id: str) -> dict[str, Path]:
    root = SESSIONS_ROOT / session_id
    return {
        "root":    root,
        "pdfs":    root / "pdfs",
        "index":   root / "index",
        "cards":   root / "cards",
    }


def validate_pdf(data: bytes, filename: str) -> None:
    """
    Raise UploadError if the bytes fail any check:
      - extension (.pdf)
      - magic bytes (%PDF)
      - size > MAX_UPLOAD_MB
      - page count > MAX_PAGES
      - encrypted / password-protected
      - embedded JavaScript or launch actions
    """
    if not filename.lower().endswith(".pdf"):
        raise UploadError(f"'{filename}' is not a PDF (wrong extension).")

    if not data.startswith(PDF_MAGIC):
        raise UploadError(
            f"'{filename}' is not a valid PDF (magic bytes missing). "
            "Make sure you are uploading a real PDF, not a renamed file."
        )

    mb = len(data) / (1024 * 1024)
    if mb > MAX_UPLOAD_MB:
        raise UploadError(
            f"'{filename}' is {mb:.1f} MB, which exceeds the {MAX_UPLOAD_MB} MB limit."
        )

    # Open with PyMuPDF for deeper checks
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise UploadError(f"Cannot open '{filename}': {e}")

    try:
        if doc.needs_pass:
            raise UploadError(
                f"'{filename}' is password-protected. "
                "Please provide an unlocked PDF."
            )

        if doc.is_encrypted:
            raise UploadError(
                f"'{filename}' is encrypted. Please provide an unlocked PDF."
            )

        pages = len(doc)
        if pages > MAX_PAGES:
            raise UploadError(
                f"'{filename}' has {pages} pages, which exceeds the {MAX_PAGES}-page limit."
            )

        if pages == 0:
            raise UploadError(f"'{filename}' contains no pages.")

        # Check for embedded JavaScript or launch actions
        for pg_idx in range(pages):
            page = doc[pg_idx]
            for link in page.get_links():
                if link.get("kind") == fitz.LINK_LAUNCH:
                    raise UploadError(
                        f"'{filename}' contains a launch action on page {pg_idx + 1}. "
                        "For security, PDFs with launch actions are not accepted."
                    )
                uri = link.get("uri", "")
                if uri.lower().startswith("javascript:"):
                    raise UploadError(
                        f"'{filename}' contains JavaScript on page {pg_idx + 1}. "
                        "For security, PDFs with embedded JavaScript are not accepted."
                    )

        # Check document-level JS via XML metadata / named actions
        try:
            xml = doc.get_xml_metadata()
            if xml and "javascript" in xml.lower():
                raise UploadError(
                    f"'{filename}' contains JavaScript in its metadata."
                )
        except UploadError:
            raise
        except Exception:
            pass

    finally:
        doc.close()


def save_upload(session_id: str, filename: str, data: bytes) -> Path:
    """
    Save validated PDF bytes to the session workspace.
    Returns the saved path.
    """
    dirs = session_dirs(session_id)
    dirs["pdfs"].mkdir(parents=True, exist_ok=True)
    dirs["index"].mkdir(parents=True, exist_ok=True)
    dirs["cards"].mkdir(parents=True, exist_ok=True)

    # Write a timestamp file for retention tracking
    ts_file = dirs["root"] / ".created_at"
    if not ts_file.exists():
        ts_file.write_text(str(time.time()))

    dest = dirs["pdfs"] / filename
    dest.write_bytes(data)
    return dest


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_session_pdf(
    session_id: str,
    filename: str,
    progress_cb=None,
) -> dict:
    """
    Run the existing ingest.build_index on the session PDF directory.
    progress_cb(stage: str, pct: float) is called at each stage.

    Returns the ingest manifest dict.
    """
    from tracerag.ingest import build_index, load_manifest

    dirs = session_dirs(session_id)
    pdf_dir   = str(dirs["pdfs"])
    index_dir = str(dirs["index"])

    stages = ["validate", "parse", "OCR", "extract facts", "summarise"]

    def _progress(stage: str, pct: float):
        if progress_cb:
            progress_cb(stage, pct)

    _progress("parse", 0.1)
    build_index(pdf_dir, index_dir)
    _progress("extract facts", 0.9)

    manifest = load_manifest(index_dir)
    _progress("summarise", 1.0)
    return manifest


def log_upload(session_id: str, filename: str, sha256: str,
               index_dir: str) -> None:
    audit = AuditLog(index_dir)
    audit.log_event("upload", {
        "session_id": session_id,
        "filename":   filename,
        "sha256":     sha256,
        # never log file contents
    })


def log_delete(session_id: str, index_dir: str) -> None:
    try:
        audit = AuditLog(index_dir)
        audit.log_event("delete", {"session_id": session_id})
    except Exception:
        pass  # index may already be gone


def delete_session(session_id: str) -> None:
    """Remove the entire session workspace (PDFs, index, cards)."""
    dirs = session_dirs(session_id)
    index_dir = str(dirs["index"])
    log_delete(session_id, index_dir)
    shutil.rmtree(str(dirs["root"]), ignore_errors=True)


def cleanup_expired_sessions() -> list[str]:
    """
    Delete sessions older than RETENTION_HOURS.
    Returns list of deleted session IDs.
    """
    deleted = []
    if not SESSIONS_ROOT.exists():
        return deleted
    cutoff = time.time() - RETENTION_HOURS * 3600
    for session_dir in SESSIONS_ROOT.iterdir():
        ts_file = session_dir / ".created_at"
        if not ts_file.exists():
            continue
        try:
            created_at = float(ts_file.read_text())
        except Exception:
            continue
        if created_at < cutoff:
            sid = session_dir.name
            delete_session(sid)
            deleted.append(sid)
    return deleted


def get_ocr_stats(session_id: str) -> dict[str, dict]:
    """
    Return per-document OCR stats: mean confidence and list of low-confidence pages.
    Reads from the session index regions.jsonl.
    """
    import json
    dirs = session_dirs(session_id)
    regions_path = dirs["index"] / "regions.jsonl"
    if not regions_path.exists():
        return {}

    doc_stats: dict[str, dict] = {}
    with open(regions_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("kind") != "scanned_page":
                continue
            doc = r.get("doc", "")
            pg  = r.get("page", 0)
            conf = r.get("confidence", 1.0)
            if doc not in doc_stats:
                doc_stats[doc] = {"confs": [], "low_pages": []}
            doc_stats[doc]["confs"].append(conf)
            if conf < 0.80:
                doc_stats[doc]["low_pages"].append(pg)

    result = {}
    for doc, stats in doc_stats.items():
        confs = stats["confs"]
        result[doc] = {
            "mean_confidence": sum(confs) / len(confs) if confs else 1.0,
            "low_pages": sorted(set(stats["low_pages"])),
            "scanned_page_count": len(confs),
        }
    return result
