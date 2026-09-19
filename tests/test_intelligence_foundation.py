from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.context_provenance import SYSTEM_POLICY, TRUSTED_KNOWLEDGE, label
from core.evaluation import get_evaluation, record_evaluation, update_evaluation
from core.memory_engine import approve_memory_candidate, create_memory_candidate, recent_turns, search_memory, supersede_memory
from core.request_context import RequestContext


class IntelligenceFoundationTests(unittest.TestCase):
    def test_future_channels_are_context_values_only(self):
        context = RequestContext("mobile_app", "telegram_user", "telegram_public", actor_id="u", session_id="s", request_id="r")
        self.assertEqual(context.channel, "mobile_app")
        self.assertEqual(context.request_id, "r")

    def test_context_provenance_is_explicit(self):
        self.assertEqual(label(SYSTEM_POLICY, "policy"), "[SYSTEM_POLICY]\npolicy")
        self.assertEqual(label(TRUSTED_KNOWLEDGE, "source"), "[TRUSTED_KNOWLEDGE]\nsource")

    def test_evaluation_lifecycle_stays_separate_from_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.db"
            self.assertTrue(record_evaluation(request_id="req-123456789", channel="portfolio_web", response="answer", session_id="session", db_path=db))
            self.assertEqual(get_evaluation("req-123456789", db)["status"], "pending")
            self.assertTrue(update_evaluation("req-123456789", status="needs_review", feedback="incorrect", correction_candidate="correct fact", db_path=db))
            result = get_evaluation("req-123456789", db)
            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["correction_candidate"], "correct fact")
            self.assertEqual(result["approval_status"], "pending")

    def test_memory_candidate_requires_approval_and_supersedes_old_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            import core.memory_engine as engine
            original = engine.DB
            engine.DB = Path(tmp) / "memory.db"
            try:
                candidate = create_memory_candidate(user_id="u1", category="stable_preference", content="prefers concise answers", importance=5)
                self.assertIsNotNone(candidate)
                self.assertEqual(search_memory("concise", user_id="u1"), [])
                self.assertTrue(approve_memory_candidate(candidate))
                self.assertEqual(len(search_memory("concise", user_id="u1")), 1)
                old = create_memory_candidate(user_id="u1", category="stable_preference", content="prefers detailed answers", importance=5)
                self.assertTrue(approve_memory_candidate(old))
                rows = search_memory("answers", user_id="u1")
                self.assertEqual(len(rows), 2)
                self.assertTrue(supersede_memory(1))
                self.assertEqual(len(search_memory("concise", user_id="u1")), 0)
            finally:
                engine.DB = original

    def test_conversation_history_is_not_training_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            import core.memory_engine as engine
            original = engine.DB
            engine.DB = Path(tmp) / "memory.db"
            try:
                self.assertTrue(engine.save_turn("s1", "u1", "user", "hello"))
                self.assertEqual(recent_turns("s1"), [("user", "hello")])
            finally:
                engine.DB = original


if __name__ == "__main__":
    unittest.main()
