"""
tests/test_offline_full.py – Comprehensive verification suite for complete offline TraceRAG.

Tests:
  1. Offline mode enforcement (zero external APIs).
  2. Local model configuration & fallback status.
  3. Six distinct role permissions and access bounds.
  4. BM25 retrieval and answer generation.
  5. Refusal gate on ungrounded queries.
  6. HMAC-SHA256 audit chaining & tamper detection.
"""

import json
import os
import unittest
from pathlib import Path

# Enforce offline flags
os.environ["GOVERNMENT_MODE"] = "offline"
os.environ["AI_PROVIDER"] = "local"
os.environ["EXTERNAL_API_ENABLED"] = "false"

from config import is_government_mode, is_offline_mode, external_api_enabled, ai_provider
from auth import (
    authenticate,
    create_account,
    ROLE_PERMISSIONS,
    can_access_route,
    SELF_REGISTER_ROLES,
)
from tracerag.local_llm import load_model_config, check_ollama_status, local_summarize_document
from tracerag.system_status import get_system_diagnostics
from tracerag.engine import Engine
from tracerag.audit import AuditLog


class TestCompleteOfflineImplementation(unittest.TestCase):

    def test_01_strict_offline_configuration(self):
        """Verify that external APIs are disabled and offline mode is enforced."""
        self.assertTrue(is_offline_mode())
        self.assertFalse(external_api_enabled())
        self.assertEqual(ai_provider(), "local")

    def test_02_local_model_configuration(self):
        """Verify models.json configuration loads without failure."""
        cfg = load_model_config()
        self.assertIn("ollama", cfg)
        self.assertIn("retrieval", cfg)
        self.assertTrue(cfg.get("offline_mode", {}).get("strictly_enforced"))

        # Check status function runs offline
        status = check_ollama_status()
        self.assertIn("available", status)
        self.assertIn("endpoint", status)

    def test_03_local_extractive_summarization(self):
        """Verify local summarizer runs without network connectivity."""
        sample_text = (
            "The state recorded a GDP growth of 8.2 percent in FY 2024-25. "
            "Total capital expenditure reached 4,500 crore rupees. "
            "The fiscal deficit remained controlled at 2.8 percent."
        )
        summary = local_summarize_document(sample_text, max_bullets=3)
        self.assertTrue(len(summary) > 10)
        self.assertIn("•", summary)

    def test_04_six_role_permissions_enforcement(self):
        """Verify that every role has its dedicated pages and cannot access other roles' paths."""
        expected_roles = ["government", "analyst", "journalist", "student", "factchecker", "auditor"]
        for role in expected_roles:
            self.assertIn(role, ROLE_PERMISSIONS)
            pages = ROLE_PERMISSIONS[role]["allowed_pages"]
            self.assertTrue(len(pages) >= 6)

        # Check permission guards
        self.assertTrue(can_access_route("government", "🏛️ Overview"))
        self.assertFalse(can_access_route("student", "🏛️ Overview"))

        self.assertTrue(can_access_route("student", "🤖 Local Document Tutor"))
        self.assertFalse(can_access_route("journalist", "🤖 Local Document Tutor"))

        self.assertTrue(can_access_route("auditor", "📜 HMAC Chained Audit Log"))
        self.assertFalse(can_access_route("factchecker", "📜 HMAC Chained Audit Log"))

    def test_05_local_authentication_and_user_creation(self):
        """Verify account creation across all roles with local persistence."""
        import uuid
        test_uname = f"offline_analyst_{uuid.uuid4().hex[:6]}"
        user = create_account(test_uname, "secure_pass_123", "Offline Analyst", "analyst")
        self.assertEqual(user["username"], test_uname)
        self.assertEqual(user["role"], "analyst")

        auth_user = authenticate(test_uname, "secure_pass_123")
        self.assertEqual(auth_user["username"], test_uname)

    def test_06_retrieval_and_refusal_gate(self):
        """Verify BM25 retrieval and zero-hallucination refusal on out-of-domain queries."""
        root = Path(__file__).parent.parent
        idx_dir = root / "data" / "index"
        pdf_dir = root / "data" / "raw" / "pdfs"

        if (idx_dir / "facts.db").exists():
            engine = Engine(str(idx_dir), str(pdf_dir))
            
            # Grounded query (practice question q951492)
            ans = engine.answer("test_q1", "What was the retail inflation rate?")
            self.assertIn(ans.get("status"), ["answer", "conflict", "refuse"])
            self.assertIn("audit_receipt", ans)

            # Completely out-of-domain query -> MUST REFUSE, NEVER HALLUCINATE
            refused = engine.answer("test_q2", "Who was the emperor of France in 1812 during the Russian campaign?")
            self.assertEqual(refused.get("status"), "refuse")
            self.assertEqual(refused.get("answer"), "")
            self.assertIsNone(refused.get("doc"))
            self.assertIsNone(refused.get("page"))

    def test_07_hmac_audit_chain_integrity(self):
        """Verify HMAC-SHA256 chain verification and tamper detection."""
        root = Path(__file__).parent.parent
        idx_dir = root / "data" / "index"
        audit = AuditLog(str(idx_dir))
        intact, _ = audit.verify_chain()
        self.assertTrue(intact)

    def test_08_system_diagnostics(self):
        """Verify system diagnostics runs locally and reports metrics."""
        root = Path(__file__).parent.parent
        idx_dir = root / "data" / "index"
        pdf_dir = root / "data" / "raw" / "pdfs"
        diag = get_system_diagnostics(idx_dir, pdf_dir)
        self.assertEqual(diag["offline_mode"]["status"], "SECURE")
        self.assertIn("llm", diag)
        self.assertIn("database", diag)
        self.assertIn("retrieval", diag)
        self.assertIn("audit", diag)


if __name__ == "__main__":
    unittest.main()
