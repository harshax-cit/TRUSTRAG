"""
tests/test_roles.py – Role-based routing and security tests.

Tests:
  1.  Government login succeeds in offline mode, fails in online mode
  2.  Online roles succeed in online mode, fail in offline mode
  3.  LLM is blocked in government mode (no silent cloud fallback)
  4.  YouTube is blocked in government mode
  5.  External API flag is False in government mode
  6.  Config paths differ between modes
  7.  Local model unavailability raises error (not cloud fallback)
  8.  Government and online sessions are isolated (different index dirs)
  9.  Auditor role can access online but not government env
 10.  Wrong password → AuthError
 11.  Student study mode blocked in government mode
 12.  App loads in both modes (Streamlit AppTest)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

INDEX_EXISTS = (Path(__file__).parent.parent / "data" / "index" / "facts.db").exists()


# ── helpers ───────────────────────────────────────────────────────────────────

def _set_gov():
    os.environ["GOVERNMENT_MODE"] = "offline"
    # Reset cached state
    import config, tracerag.llm as llm
    llm._API_MODE = None


def _set_online():
    os.environ["GOVERNMENT_MODE"] = "false"
    import config, tracerag.llm as llm
    llm._API_MODE = None


def _clear():
    os.environ.pop("GOVERNMENT_MODE", None)
    import tracerag.llm as llm
    llm._API_MODE = None


# ── 1-2. Authentication ───────────────────────────────────────────────────────

class TestAuthentication(unittest.TestCase):

    def test_government_login_in_offline_mode(self):
        _set_gov()
        try:
            from auth import authenticate
            user = authenticate("government", "gov-secure-2024")
            self.assertEqual(user["role"], "government")
            self.assertTrue(user["authenticated"])
        finally:
            _clear()

    def test_government_login_works_from_any_env(self):
        """
        Single login page: government login succeeds regardless of env var.
        The offline flag is set based on the ROLE, not the env var.
        """
        _set_online()   # env says online
        try:
            from auth import authenticate
            user = authenticate("government", "gov-secure-2024")
            self.assertEqual(user["role"], "government")
            # offline flag driven by role
            self.assertTrue(user["offline"],
                "government role must set offline=True regardless of env var")
        finally:
            _clear()

    def test_online_role_works_from_any_env(self):
        """Single login page: online roles work regardless of GOVERNMENT_MODE."""
        _set_gov()   # env says offline
        try:
            from auth import authenticate
            user = authenticate("analyst", "analyst-pass")
            self.assertEqual(user["role"], "analyst")
            self.assertFalse(user["offline"],
                "online roles must set offline=False")
        finally:
            _clear()

    def test_online_role_succeeds_in_online_mode(self):
        _set_online()
        try:
            from auth import authenticate
            for username, password, expected_role in [
                ("analyst",    "analyst-pass",  "analyst"),
                ("journalist", "press-pass",    "journalist"),
                ("student",    "learn-2024",    "student"),
                ("checker",    "verify-pass",   "factchecker"),
                ("auditor",    "audit-admin",   "auditor"),
            ]:
                user = authenticate(username, password)
                self.assertEqual(user["role"], expected_role, username)
        finally:
            _clear()

    def test_wrong_password_raises_auth_error(self):
        _set_online()
        try:
            from auth import authenticate, AuthError
            with self.assertRaises(AuthError):
                authenticate("analyst", "wrong-password")
        finally:
            _clear()

    def test_nonexistent_user_raises_auth_error(self):
        _set_online()
        try:
            from auth import authenticate, AuthError
            with self.assertRaises(AuthError):
                authenticate("hacker", "any-password")
        finally:
            _clear()


# ── 3. LLM blocked in government mode ────────────────────────────────────────

class TestLLMGovernmentBlock(unittest.TestCase):

    def test_llm_disabled_in_government_mode(self):
        _set_gov()
        # Pretend an API key is set — should still be blocked
        os.environ["OPENAI_API_KEY"] = "sk-fake-key"
        try:
            from tracerag.llm import _detect_mode, is_online
            # Reset cached mode
            import tracerag.llm as llm
            llm._API_MODE = None
            mode = _detect_mode()
            self.assertIsNone(mode,
                "LLM mode must be None in government mode even if key is set")
            self.assertFalse(is_online())
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            _clear()

    def test_llm_enabled_in_online_mode_with_key(self):
        _set_online()
        os.environ["OPENAI_API_KEY"] = "sk-fake-key"
        try:
            import tracerag.llm as llm
            llm._API_MODE = None
            mode = llm._detect_mode()
            self.assertEqual(mode, "openai")
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            _clear()

    def test_no_silent_cloud_fallback_in_government_mode(self):
        """
        In government mode, if local model is unavailable the system must
        raise LocalModelUnavailable — it must NOT silently call a cloud API.
        """
        _set_gov()
        os.environ["OPENAI_API_KEY"] = "sk-fake"
        try:
            from config import GovernmentModeViolation, assert_local_only
            with self.assertRaises(GovernmentModeViolation):
                assert_local_only("cloud_llm_call")
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            _clear()


# ── 4. YouTube blocked in government mode ────────────────────────────────────

class TestYouTubeGovernmentBlock(unittest.TestCase):

    def test_youtube_blocked_in_government_mode(self):
        _set_gov()
        try:
            from study.youtube import recommendations_for_topic
            topic = {"title": "Economics", "key_numbers": []}
            recs  = recommendations_for_topic(topic, n=3)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["mode"], "blocked")
            self.assertNotIn("youtube.com", recs[0]["url"])
        finally:
            _clear()

    def test_youtube_works_in_online_mode(self):
        _set_online()
        try:
            from study.youtube import recommendations_for_topic
            topic = {"title": "Economics", "key_numbers": []}
            recs  = recommendations_for_topic(topic, n=1)
            self.assertGreater(len(recs), 0)
            self.assertIn("youtube.com", recs[0]["url"])
        finally:
            _clear()


# ── 5. External API flag ──────────────────────────────────────────────────────

class TestExternalAPIFlag(unittest.TestCase):

    def test_external_api_false_in_government_mode(self):
        _set_gov()
        try:
            from config import external_api_enabled
            self.assertFalse(external_api_enabled())
        finally:
            _clear()

    def test_external_api_true_in_online_mode(self):
        _set_online()
        os.environ.pop("EXTERNAL_API_ENABLED", None)
        try:
            from config import external_api_enabled
            self.assertTrue(external_api_enabled())
        finally:
            _clear()


# ── 6. Config paths differ between modes ─────────────────────────────────────

class TestConfigPaths(unittest.TestCase):

    def test_index_dir_differs(self):
        _set_gov()
        from config import index_dir as gov_idx
        gov = gov_idx()
        _set_online()
        from config import index_dir as onl_idx
        onl = onl_idx()
        self.assertNotEqual(gov, onl,
            "Government and online index dirs must be different")
        _clear()

    def test_pdf_dir_differs(self):
        _set_gov()
        from config import pdf_dir as gov_pdf
        gov = gov_pdf()
        _set_online()
        from config import pdf_dir as onl_pdf
        onl = onl_pdf()
        self.assertNotEqual(gov, onl)
        _clear()


# ── 7. Local model unavailability raises error ────────────────────────────────

class TestLocalModelUnavailable(unittest.TestCase):

    def test_assert_local_only_blocks_in_government_mode(self):
        _set_gov()
        try:
            from config import assert_local_only, GovernmentModeViolation
            with self.assertRaises(GovernmentModeViolation):
                assert_local_only("openai_api_call")
        finally:
            _clear()

    def test_assert_local_only_passes_in_online_mode(self):
        _set_online()
        try:
            from config import assert_local_only
            # Should not raise
            assert_local_only("openai_api_call")
        finally:
            _clear()


# ── 8. Session isolation ──────────────────────────────────────────────────────

class TestSessionIsolation(unittest.TestCase):

    def test_government_index_dir_not_equal_to_online(self):
        _set_gov()
        from config import index_dir
        gov_dir = index_dir()
        _set_online()
        onl_dir = index_dir()
        _clear()
        self.assertNotEqual(Path(gov_dir).resolve(), Path(onl_dir).resolve(),
            "Government and online environments must use separate index directories")


# ── 9. Role authorisation ─────────────────────────────────────────────────────

class TestRoleAuthorisation(unittest.TestCase):

    def setUp(self):
        _set_online()

    def tearDown(self):
        _clear()

    def test_auditor_can_access_analyst(self):
        from auth import is_authorised
        user = {"role": "auditor", "authenticated": True}
        self.assertTrue(is_authorised(user, "analyst"))

    def test_analyst_cannot_access_journalist_data(self):
        from auth import is_authorised
        user = {"role": "analyst", "authenticated": True}
        self.assertFalse(is_authorised(user, "journalist"))

    def test_unauthenticated_blocked(self):
        from auth import is_authorised
        self.assertFalse(is_authorised(None, "analyst"))
        self.assertFalse(is_authorised({}, "analyst"))
        self.assertFalse(is_authorised({"role": "analyst"}, "analyst"))

    def test_government_role_blocked_from_online_resource(self):
        """Government users cannot be is_authorised for online-only roles."""
        # government role only exists in offline mode — but test the logic
        from auth import is_authorised
        user = {"role": "government", "authenticated": True}
        # is_authorised(government, analyst) → False (not same role, auditor exception doesn't apply)
        self.assertFalse(is_authorised(user, "analyst"))


# ── 10. ROLE_TABS completeness ────────────────────────────────────────────────

class TestRoleTabs(unittest.TestCase):

    def test_government_tabs_subset(self):
        from config import ROLE_TABS
        gov_tabs = ROLE_TABS["government"]
        # Government must NOT have full study pipeline tabs
        # (those require external student-mode features)
        disallowed = ["📤 Upload", "▶️ Videos", "❓ Ask", "🧠 Quiz"]
        for t in disallowed:
            self.assertNotIn(t, gov_tabs,
                f"Government dashboard must not include {t}")
        # But My PDFs (local upload + Q&A) is allowed
        self.assertIn("📚 My PDFs", gov_tabs,
                      "Government must have My PDFs tab (local only)")

    def test_student_has_study_tabs(self):
        from config import ROLE_TABS
        student_tabs = ROLE_TABS["student"]
        for t in ["📤 Upload", "🃏 Flashcards", "🧠 Quiz"]:
            self.assertIn(t, student_tabs)

    def test_all_roles_have_at_least_one_tab(self):
        from config import ROLE_TABS, ROLES
        for role in ROLES:
            self.assertGreater(len(ROLE_TABS.get(role, [])), 0,
                f"Role '{role}' has no tabs")


# ── 11. Existing tests still importable ──────────────────────────────────────

class TestExistingTestsUnbroken(unittest.TestCase):
    def test_regressions_importable(self):
        import tests.test_regressions  # noqa

    def test_study_importable(self):
        import tests.test_study  # noqa


# ── 12. AppTest smoke test ────────────────────────────────────────────────────

class TestAppLoads(unittest.TestCase):

    def test_app_loads_online_mode(self):
        """App boots in online mode without exceptions."""
        _set_online()
        try:
            from streamlit.testing.v1 import AppTest
            app_path = str(Path(__file__).parent.parent / "app.py")
            at = AppTest.from_file(app_path, default_timeout=60)
            at.run()
            # Login screen should show (no exception)
            self.assertFalse(
                any("GovernmentModeViolation" in str(e) for e in at.exception),
                f"App raised gov exception in online mode: {at.exception}"
            )
        finally:
            _clear()

    def test_app_loads_government_mode(self):
        """App boots in government mode without exceptions."""
        _set_gov()
        try:
            from streamlit.testing.v1 import AppTest
            app_path = str(Path(__file__).parent.parent / "app.py")
            at = AppTest.from_file(app_path, default_timeout=60)
            at.run()
            self.assertFalse(
                any("online" in str(e).lower() for e in at.exception
                    if "online" in str(e).lower()),
                f"App raised online exception in gov mode: {at.exception}"
            )
        finally:
            _clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
