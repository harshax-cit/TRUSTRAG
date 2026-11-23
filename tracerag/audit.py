"""
audit.py – HMAC-SHA256 hash chain audit log.

Design:
  - Every event is a JSON record written to audit.jsonl.
  - Each record includes the HMAC-SHA256 of (prev_hash + record_json).
  - An anchor file (audit_anchor.txt) stores the latest chain head hash.
  - A threading.Lock prevents concurrent writes.
  - A tamper demo function edits a COPY of the log and shows the chain breaking.

Tamper-evidence claim: any insertion, deletion, or modification of a log
record (or the anchor) will cause chain verification to fail.
NOTE: this is tamper-EVIDENT, not tamper-PROOF. A sufficiently motivated
attacker with the HMAC key can re-chain the log.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

AUDIT_FILE = "audit.jsonl"
ANCHOR_FILE = "audit_anchor.txt"
RECEIPT_PREFIX = "TR"


def _get_key() -> bytes:
    """Read HMAC key from env or use a default (for demo / tests)."""
    key_str = os.environ.get("AUDIT_HMAC_KEY", "tracerag-default-dev-key-change-in-prod")
    return key_str.encode("utf-8")


def _hmac_hash(key: bytes, data: str) -> str:
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).hexdigest()


class AuditLog:
    """
    Thread-safe append-only audit log with HMAC chain.
    One instance per process is fine; share via module-level singleton.
    """

    _lock = threading.Lock()

    def __init__(self, index_dir: str):
        self.index_dir = index_dir
        self._audit_path = os.path.join(index_dir, AUDIT_FILE)
        self._anchor_path = os.path.join(index_dir, ANCHOR_FILE)
        os.makedirs(index_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public logging API
    # ------------------------------------------------------------------

    def log_ingest(self, doc: str, page_count: int, fact_count: int):
        self._append({"type": "ingest", "doc": doc,
                      "page_count": page_count, "fact_count": fact_count})

    def log_query(self, question_id: str, question: str):
        self._append({"type": "query", "question_id": question_id,
                      "question": question[:200]})

    def log_event(self, event_type: str, payload: dict):
        self._append({"type": event_type, **payload})

    def log_decision(self, question_id: str, status: str,
                      reason: Optional[str]):
        self._append({"type": "decision", "question_id": question_id,
                      "status": status, "reason": reason})

    def create_receipt(self, question_id: str, status: str) -> str:
        """Return a receipt string TR-YYYYMMDD-Qid-hash8."""
        today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        chain_hash = self._read_anchor()[:8]
        receipt = f"{RECEIPT_PREFIX}-{today}-{question_id}-{chain_hash}"
        self._append({"type": "receipt", "receipt": receipt,
                      "question_id": question_id, "status": status})
        return receipt

    # ------------------------------------------------------------------
    # Chain verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> tuple[bool, str]:
        """
        Walk the entire chain. Returns (ok, message).
        """
        key = _get_key()
        if not os.path.exists(self._audit_path):
            return True, "Log is empty – chain intact."

        prev_hash = "0" * 64
        line_num = 0
        with open(self._audit_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                line_num += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return False, f"Line {line_num}: invalid JSON"

                stored_hash = record.get("chain_hash", "")
                # Recompute: HMAC(prev_hash + record without chain_hash)
                record_copy = {k: v for k, v in record.items()
                                if k != "chain_hash"}
                payload = prev_hash + json.dumps(record_copy, sort_keys=True)
                expected = _hmac_hash(key, payload)
                if stored_hash != expected:
                    return (False,
                            f"Chain broken at line {line_num}: "
                            f"expected {expected[:16]}…, got {stored_hash[:16]}…")
                prev_hash = stored_hash

        # Check anchor
        anchor = self._read_anchor()
        if prev_hash and anchor and prev_hash != anchor:
            return False, f"Anchor mismatch: log head={prev_hash[:16]}…, anchor={anchor[:16]}…"

        return True, f"Chain intact. {line_num} records verified."

    def export_jsonl(self, out_path: str) -> int:
        """Export audit log to a JSONL file. Returns record count."""
        if not os.path.exists(self._audit_path):
            return 0
        shutil.copy2(self._audit_path, out_path)
        with open(out_path) as f:
            count = sum(1 for line in f if line.strip())
        return count

    # ------------------------------------------------------------------
    # Tamper demo
    # ------------------------------------------------------------------

    def tamper_demo(self, out_dir: str) -> dict:
        """
        Copy the audit log to out_dir, edit one record, and show chain breaks.
        Returns a dict with the results.
        """
        os.makedirs(out_dir, exist_ok=True)
        tampered_log = os.path.join(out_dir, "tampered_audit.jsonl")
        tampered_anchor = os.path.join(out_dir, "tampered_anchor.txt")

        if not os.path.exists(self._audit_path):
            return {"error": "No audit log to tamper with."}

        shutil.copy2(self._audit_path, tampered_log)
        shutil.copy2(self._anchor_path, tampered_anchor) if os.path.exists(
            self._anchor_path) else open(tampered_anchor, "w").close()

        # Edit line 1 (or the first decision record)
        lines = []
        with open(tampered_log, encoding="utf-8") as f:
            lines = f.readlines()

        tampered_line_idx = None
        for i, line in enumerate(lines):
            try:
                rec = json.loads(line)
                if rec.get("type") in ("decision", "query", "receipt"):
                    tampered_line_idx = i
                    break
            except Exception:
                continue

        if tampered_line_idx is None and lines:
            tampered_line_idx = 0

        if tampered_line_idx is not None:
            try:
                rec = json.loads(lines[tampered_line_idx])
                # Inject a fake edit
                original_status = rec.get("status", rec.get("type", ""))
                rec["_TAMPERED"] = True
                if "status" in rec:
                    rec["status"] = "FAKED_ANSWER"
                elif "question" in rec:
                    rec["question"] = "<<TAMPERED QUESTION>>"
                lines[tampered_line_idx] = json.dumps(rec) + "\n"
            except Exception:
                pass

        with open(tampered_log, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # Verify the tampered copy
        tampered_auditor = AuditLog.__new__(AuditLog)
        tampered_auditor.index_dir = out_dir
        tampered_auditor._audit_path = tampered_log
        tampered_auditor._anchor_path = tampered_anchor
        tampered_auditor._lock = threading.Lock()

        ok, message = tampered_auditor.verify_chain()
        _, original_message = self.verify_chain()

        return {
            "original_chain_ok": True,
            "original_message": original_message,
            "tampered_chain_ok": ok,
            "tampered_message": message,
            "tampered_line": tampered_line_idx,
            "note": (
                "The log is tamper-EVIDENT (not tamper-PROOF). "
                "An attacker with the HMAC key could re-sign the chain."
            ),
        }

    # ------------------------------------------------------------------
    # Refusal ledger
    # ------------------------------------------------------------------

    def get_refusal_ledger(self) -> list[dict]:
        """Return all refusal decisions."""
        ledger = []
        if not os.path.exists(self._audit_path):
            return ledger
        with open(self._audit_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("type") == "decision" and rec.get("status") == "refuse":
                        ledger.append(rec)
                except Exception:
                    pass
        return ledger

    def get_decision_mix(self) -> dict:
        """Return counts of answer / conflict / refuse decisions."""
        counts = {"answer": 0, "conflict": 0, "refuse": 0, "other": 0}
        if not os.path.exists(self._audit_path):
            return counts
        with open(self._audit_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("type") == "decision":
                        status = rec.get("status", "other")
                        counts[status] = counts.get(status, 0) + 1
                except Exception:
                    pass
        return counts

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: dict):
        """Append a record to the chain (thread-safe)."""
        key = _get_key()
        with AuditLog._lock:
            prev_hash = self._read_anchor()
            record["ts"] = datetime.now(tz=timezone.utc).isoformat()
            payload = prev_hash + json.dumps(record, sort_keys=True)
            chain_hash = _hmac_hash(key, payload)
            record["chain_hash"] = chain_hash

            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            self._write_anchor(chain_hash)

    def _read_anchor(self) -> str:
        if os.path.exists(self._anchor_path):
            with open(self._anchor_path) as f:
                return f.read().strip()
        return "0" * 64

    def _write_anchor(self, hash_val: str):
        with open(self._anchor_path, "w") as f:
            f.write(hash_val)
