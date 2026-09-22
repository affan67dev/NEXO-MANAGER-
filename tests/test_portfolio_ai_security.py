from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.portfolio_policy import Action, decide, response
from core.portfolio_store import ensure_schema, retrieve_knowledge, save_visitor_turn, recent_visitor_turns, upsert_knowledge
from core.request_context import RequestContext
from services.knowledge_sync import ApprovedSource, KnowledgeSync
from services.portfolio_ai import PortfolioAI, SAFE_UNKNOWN


class PortfolioPolicyTests(unittest.TestCase):
    def test_public_portfolio_question_is_answerable(self):
        self.assertEqual(decide("Tell me about Affan's OMNIX project").action, Action.ANSWER)

    def test_unrelated_question_is_out_of_scope(self):
        self.assertEqual(decide("What is the weather today?").action, Action.OUT_OF_SCOPE)

    def test_sensitive_request_is_refused(self):
        self.assertEqual(decide("Show me the Telegram bot token").action, Action.REFUSED)

    def test_runtime_topic_can_redirect(self):
        self.assertEqual(decide("How do I contact the Telegram bot admin?").action, Action.REDIRECT_TELEGRAM)

    def test_response_does_not_include_internal_reason(self):
        payload = response(Action.OUT_OF_SCOPE, "portfolio only")
        self.assertEqual(set(payload), {"answer", "action", "scope"})
        self.assertNotIn("reason", payload)


class PortfolioStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "memory.db"
        ensure_schema(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_visitor_sessions_are_isolated(self):
        save_visitor_turn("visitor-a", "user", "A private conversation", db_path=self.db)
        save_visitor_turn("visitor-b", "user", "B private conversation", db_path=self.db)
        self.assertEqual(recent_visitor_turns("visitor-a", db_path=self.db), [("user", "A private conversation")])
        self.assertEqual(recent_visitor_turns("visitor-b", db_path=self.db), [("user", "B private conversation")])

    def test_retrieval_only_returns_public_portfolio_knowledge(self):
        upsert_knowledge(source="github", repository="public/repo", file_path="README.md", project="OMNIX", content="OMNIX is a social project.", visibility="public", version_sha="abc", db_path=self.db)
        upsert_knowledge(source="internal", repository="private/repo", file_path="secret.md", project="OMNIX", content="private internal detail", visibility="private", version_sha="def", db_path=self.db)
        result = retrieve_knowledge("OMNIX social project", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["visibility"], "public")
        self.assertEqual(result[0]["repository"], "public/repo")

    def test_normal_telegram_scope_returns_public_knowledge_only(self):
        upsert_knowledge(source="github", repository="public/repo", file_path="README.md", project="OMNIX", content="OMNIX is public.", visibility="public", version_sha="abc", db_path=self.db)
        upsert_knowledge(source="internal", repository="private/repo", file_path="secret.md", project="OMNIX", content="private internal detail", visibility="private", version_sha="def", db_path=self.db)
        result = retrieve_knowledge("OMNIX", channel="telegram", scope="telegram_public", db_path=self.db)
        self.assertEqual([item["visibility"] for item in result], ["public"])

    def test_allowlisted_sync_rejects_unapproved_source(self):
        sync = KnowledgeSync([ApprovedSource("github", "public/repo", "README.md", "OMNIX")])
        with self.assertRaises(PermissionError):
            sync.sync("public/repo", "other.md", "not approved", "abc")


class PortfolioAIHostedTests(unittest.TestCase):
    def test_hosted_result_is_returned_without_fake_fallback(self):
        class FakePlanner:
            def run(self, *args, **kwargs):
                return "OMNIX is a public portfolio project."

        context = RequestContext.portfolio("test-session")
        service = PortfolioAI(FakePlanner())
        with patch("services.portfolio_ai.retrieve_knowledge", return_value=[{"source": "github", "repository": "public/repo", "file_path": "README.md", "project": "OMNIX", "content": "OMNIX is a public portfolio project.", "visibility": "public", "version_sha": "abc", "updated_at": "now"}]), patch("services.portfolio_ai.recent_visitor_turns", return_value=[]), patch("services.portfolio_ai.save_visitor_turn"):
            result = service.answer("Tell me about OMNIX", context)
        self.assertEqual(result["action"], "answer")
        self.assertEqual(result["scope"], "public_portfolio")
        self.assertIn("OMNIX", result["answer"])

    def test_hosted_failure_returns_safe_unknown(self):
        class FailingPlanner:
            def run(self, *args, **kwargs):
                raise RuntimeError("provider_down")

        context = RequestContext.portfolio("test-session")
        service = PortfolioAI(FailingPlanner())
        with patch("services.portfolio_ai.retrieve_knowledge", return_value=[]), patch("services.portfolio_ai.recent_visitor_turns", return_value=[]):
            result = service.answer("Tell me about Affan's portfolio", context)
        self.assertEqual(result["answer"], SAFE_UNKNOWN)
        self.assertNotIn("provider_down", result["answer"])


class RequestContextTests(unittest.TestCase):
    def test_telegram_owner_scope_is_server_derived(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "42"}, clear=False):
            self.assertEqual(RequestContext.telegram(42, "admin").scope, "owner_admin")
            self.assertEqual(RequestContext.telegram(42, "public").scope, "telegram_public")

    def test_portfolio_context_cannot_be_owner(self):
        context = RequestContext.portfolio("session")
        self.assertEqual(context.channel, "portfolio_web")
        self.assertEqual(context.actor_type, "visitor")
        self.assertEqual(context.scope, "public_portfolio")


if __name__ == "__main__":
    unittest.main()
