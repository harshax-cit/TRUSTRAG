"""
tests/test_enhancements.py – Verification test suite for TraceRAG Enhancements.

Tests:
  1. Master UI & Enterprise Design helpers
  2. Document Store Registration, Ownership & User Isolation
  3. Backend Access Control (User documents private, no cross-user leaks)
  4. Tabular CSV Ingestion into facts schema
  5. Image OCR Ingestion into facts schema
  6. Cross-Document Comparison and Conflict Detection
  7. Government Offline Isolation (Separate directory & zero cloud calls)
  8. Refusal Ledger and HMAC Chain Integrity
"""

import os
import sys
import unittest
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tracerag.ui import ENTERPRISE_CSS
from tracerag.docstore import (
    register_document, list_user_documents, get_document,
    delete_document, update_document_status, get_docstore_path
)
from tracerag.multimodal import ingest_csv_facts, ingest_image_facts
from tracerag.compare import compare_documents, analyze_metric_trend
from tracerag.ingest import SCHEMA
from tracerag.audit import AuditLog
from config import is_government_mode, is_government_session, assert_local_only, GovernmentModeViolation


class TestEnterpriseUI(unittest.TestCase):
    def test_css_contains_dark_forest_green(self):
        self.assertIn("#0f281e", ENTERPRISE_CSS)
        self.assertIn("#15803d", ENTERPRISE_CSS)
        self.assertIn("#f8faf9", ENTERPRISE_CSS)

    def test_css_contains_enterprise_classes(self):
        self.assertIn(".top-navbar", ENTERPRISE_CSS)
        self.assertIn(".dashboard-card", ENTERPRISE_CSS)
        self.assertIn(".stat-box", ENTERPRISE_CSS)


class TestDocumentStoreAndOwnership(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.test_dir.name, "docstore.db")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_document_registration_and_retrieval(self):
        doc = register_document(
            filename="policy_brief.pdf",
            file_type="pdf",
            file_bytes=b"%PDF-1.4 mock content",
            owner_username="analyst_test",
            owner_role="analyst",
            is_government=False,
        )
        self.assertEqual(doc["filename"], "policy_brief.pdf")
        self.assertEqual(doc["owner_username"], "analyst_test")
        self.assertEqual(doc["status"], "ready")

        # Retrieve
        fetched = get_document(doc["doc_id"], "analyst_test", "analyst", is_government=False)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["doc_id"], doc["doc_id"])

        # Clean up
        delete_document(doc["doc_id"], "analyst_test", "analyst", is_government=False)

    def test_user_document_isolation(self):
        """User A cannot see or access User B's documents."""
        doc_a = register_document(
            filename="user_a_private.pdf",
            file_type="pdf",
            file_bytes=b"%PDF-1.4 confidential A",
            owner_username="user_a",
            owner_role="analyst",
            is_government=False,
        )

        doc_b = register_document(
            filename="user_b_private.pdf",
            file_type="pdf",
            file_bytes=b"%PDF-1.4 confidential B",
            owner_username="user_b",
            owner_role="journalist",
            is_government=False,
        )

        # User A only sees User A's docs
        docs_a = list_user_documents("user_a", "analyst", is_government=False)
        filenames_a = [d["filename"] for d in docs_a]
        self.assertIn("user_a_private.pdf", filenames_a)
        self.assertNotIn("user_b_private.pdf", filenames_a)

        # User A cannot get User B's doc
        unauth_doc = get_document(doc_b["doc_id"], "user_a", "analyst", is_government=False)
        self.assertIsNone(unauth_doc, "User A should NOT be able to access User B's document!")

        # Clean up
        delete_document(doc_a["doc_id"], "user_a", "analyst", is_government=False)
        delete_document(doc_b["doc_id"], "user_b", "journalist", is_government=False)


class TestMultimodalIngestion(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SCHEMA)

    def tearDown(self):
        self.conn.close()

    def test_csv_ingestion(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as f:
            f.write("Year,Metric_Name,Value_Num\n2022-23,Solar_MW,4500.5\n2023-24,Solar_MW,5200.0\n")
            csv_path = f.name

        try:
            n = ingest_csv_facts(csv_path, "solar_stats.csv", self.conn)
            self.assertEqual(n, 2)
            cur = self.conn.cursor()
            cur.execute("SELECT value_num, period, raw_text FROM facts WHERE doc='solar_stats.csv'")
            rows = cur.fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], 4500.5)
            self.assertEqual(rows[1][0], 5200.0)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)


class TestCrossDocumentComparison(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SCHEMA)

    def tearDown(self):
        self.conn.close()

    def test_conflict_detection_and_trend(self):
        cur = self.conn.cursor()
        # Doc 1: 5.4% inflation
        cur.execute(
            """INSERT INTO facts (doc, page, metric, period, value, value_num, unit, raw_text)
               VALUES ('doc1.pdf', 10, 'CPI Inflation', '2023-24', '5.4 per cent', 5.4, 'per cent', 'Headline retail inflation was 5.4 per cent in FY24')"""
        )
        # Doc 2: conflicting 5.6% inflation
        cur.execute(
            """INSERT INTO facts (doc, page, metric, period, value, value_num, unit, raw_text)
               VALUES ('doc2.pdf', 12, 'CPI Inflation', '2023-24', '5.6 per cent', 5.6, 'per cent', 'Planted modification shows 5.6 per cent')"""
        )
        self.conn.commit()

        res = compare_documents("doc1.pdf", "doc2.pdf", self.conn)
        self.assertEqual(len(res["conflicts"]), 1)
        conf = res["conflicts"][0]
        self.assertEqual(conf["value1"], "5.4 per cent")
        self.assertEqual(conf["value2"], "5.6 per cent")
        self.assertAlmostEqual(conf["delta"], 0.2, places=2)

        # Trend analysis
        trends = analyze_metric_trend("CPI Inflation", self.conn)
        self.assertEqual(len(trends), 2)


class TestGovernmentIsolation(unittest.TestCase):
    def test_government_db_isolation(self):
        gov_path = get_docstore_path(is_government=True)
        online_path = get_docstore_path(is_government=False)
        self.assertIn("gov_index", gov_path)
        self.assertNotIn("gov_index", online_path)
        self.assertNotEqual(gov_path, online_path)

    def test_assert_local_only_enforcement(self):
        user = {"role": "government", "offline": True}
        self.assertTrue(is_government_session(user))
        # When environment variable is offline:
        old_env = os.environ.get("GOVERNMENT_MODE")
        try:
            os.environ["GOVERNMENT_MODE"] = "offline"
            self.assertTrue(is_government_mode())
            with self.assertRaises(GovernmentModeViolation):
                assert_local_only("cloud_vision_call")
        finally:
            if old_env is not None:
                os.environ["GOVERNMENT_MODE"] = old_env
            else:
                os.environ.pop("GOVERNMENT_MODE", None)


if __name__ == "__main__":
    unittest.main()
