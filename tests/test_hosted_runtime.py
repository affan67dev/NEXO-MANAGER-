from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.portfolio_store import ensure_schema, retrieve_knowledge, upsert_knowledge
from core.request_context import RequestContext
from telegram_llama import build_llm_messages


class HostedKnowledgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "memory.db"
        ensure_schema(self.db)
        upsert_knowledge(source="github", repository="public/repo", file_path="README.md", project="OMNIX", content="OMNIX is a public social project.", visibility="public", version_sha="pub", db_path=self.db)
        upsert_knowledge(source="internal", repository="private/repo", file_path="secret.md", project="OMNIX", content="private admin detail", visibility="private", version_sha="priv", db_path=self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_portfolio_context_is_server_derived(self):
        context = RequestContext.portfolio("visitor-session")
        self.assertEqual((context.channel, context.actor_type, context.scope), ("portfolio_web", "visitor", "public_portfolio"))

    def test_portfolio_can_only_retrieve_public_knowledge(self):
        result = retrieve_knowledge("OMNIX social project", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        self.assertEqual([item["visibility"] for item in result], ["public"])

    def test_normal_telegram_user_can_only_retrieve_public_knowledge(self):
        result = retrieve_knowledge("OMNIX admin detail", channel="telegram", scope="telegram_public", db_path=self.db)
        self.assertTrue(all(item["visibility"] == "public" for item in result))

    def test_owner_telegram_scope_can_retrieve_authorized_private_knowledge(self):
        result = retrieve_knowledge("OMNIX private admin detail", channel="telegram", scope="owner_admin", db_path=self.db)
        self.assertTrue(any(item["visibility"] == "private" for item in result))

    def test_bootstrap_scripts_have_no_local_llm_dependency(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("scripts/bootstrap_nexo.py", "scripts/auto_update.sh", "scripts/bootstrap_nexo_deploy.sh"):
            text = (root / relative).read_text(encoding="utf-8")
            for marker in ("LLAMA_SERVER", "NEXO_MODEL_PATH", "llama-server", "127.0.0.1:8080", "GGUF"):
                self.assertNotIn(marker, text, f"{relative}: {marker}")

    def test_telegram_model_context_is_bounded(self):
        messages = build_llm_messages("Tell me about OMNIX", [], "", "PUBLIC KNOWLEDGE")
        self.assertIn("Authorized NEXO knowledge", " ".join(m["content"] for m in messages if m.get("role") == "system"))
        self.assertEqual(messages[-1]["content"], "Tell me about OMNIX")

    def test_production_runtime_has_no_qwen_endpoint_configuration(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("agents/executive_planner.py", "services/llm_router.py", "services/context_budget.py", "services/portfolio_ai.py", "telegram_llama.py", "voice_engine.py"):
            text = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn("NEXO_QWEN_URL", text, relative)
            self.assertNotIn("127.0.0.1:8080", text, relative)


if __name__ == "__main__":
    unittest.main()
