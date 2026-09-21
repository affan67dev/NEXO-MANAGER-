from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.portfolio_store import ensure_schema, retrieve_knowledge
from services.public_knowledge_refresh import PublicKnowledgeRefresher


class FakeResponse:
    def __init__(self, data: dict, text: str = "") -> None:
        self._data = data
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def get(self, path: str):
        return self.response


class PublicKnowledgeRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "memory.db"
        ensure_schema(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_public_readme_is_ingested_with_metadata(self) -> None:
        readme = "# OMNIX\n\nOMNIX is a public project using Python and web technologies."
        response = FakeResponse(
            {
                "type": "file",
                "name": "README.md",
                "sha": "sha-1",
                "content": base64.b64encode(readme.encode()).decode(),
            }
        )
        with patch.dict("os.environ", {"NEXO_PUBLIC_GITHUB_REPOSITORIES": "OMNIX"}, clear=False):
            result = PublicKnowledgeRefresher(FakeClient(response), db_path=str(self.db)).refresh()

        self.assertEqual(result["sources"][0]["status"], "refreshed")
        docs = retrieve_knowledge("OMNIX Python", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source_type"], "github_readme")
        self.assertEqual(docs[0]["repository"], "affan67dev/OMNIX")
        self.assertEqual(docs[0]["scope"], "public_portfolio")
        self.assertEqual(docs[0]["visibility"], "public")
        self.assertEqual(docs[0]["version_sha"], "sha-1")
        self.assertTrue(docs[0]["source_url"].startswith("https://github.com/affan67dev/OMNIX/"))

    def test_unchanged_readme_is_not_reinserted(self) -> None:
        readme = "# OMNIX\n\nPublic project."
        response = FakeResponse(
            {
                "type": "file",
                "name": "README.md",
                "sha": "same-sha",
                "content": base64.b64encode(readme.encode()).decode(),
            }
        )
        with patch.dict("os.environ", {"NEXO_PUBLIC_GITHUB_REPOSITORIES": "OMNIX"}, clear=False):
            first = PublicKnowledgeRefresher(FakeClient(response), db_path=str(self.db)).refresh()
            second = PublicKnowledgeRefresher(FakeClient(response), db_path=str(self.db)).refresh()

        self.assertEqual(first["sources"][0]["status"], "refreshed")
        self.assertEqual(second["sources"][0]["status"], "unchanged")
        docs = retrieve_knowledge("OMNIX project", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        self.assertEqual(len(docs), 1)

    def test_sensitive_configuration_lines_are_not_indexed(self) -> None:
        readme = "# Project\n\nLLM_API_KEY=real-secret-value\n\nThis is public."
        response = FakeResponse(
            {
                "type": "file",
                "name": "README.md",
                "sha": "sha-safe",
                "content": base64.b64encode(readme.encode()).decode(),
            }
        )
        with patch.dict("os.environ", {"NEXO_PUBLIC_GITHUB_REPOSITORIES": "OMNIX"}, clear=False):
            PublicKnowledgeRefresher(FakeClient(response), db_path=str(self.db)).refresh()

        docs = retrieve_knowledge("Project public", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        self.assertEqual(len(docs), 1)
        self.assertNotIn("real-secret-value", docs[0]["content"])

    def test_public_scope_cannot_retrieve_private_documents(self) -> None:
        from core.portfolio_store import upsert_knowledge

        upsert_knowledge(
            source="internal",
            source_type="internal",
            repository="affan67dev/private",
            file_path="secret.md",
            project="Private",
            content="private data",
            visibility="private",
            scope="owner_admin",
            version_sha="private-1",
            db_path=self.db,
        )
        docs = retrieve_knowledge("private data", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        self.assertEqual(docs, [])

    def test_internal_readme_sections_are_excluded(self) -> None:
        readme = "# Project\n\nPublic description.\n\n## Configuration\n\nTELEGRAM_BOT_TOKEN=hidden\n\n## Features\n\nPublic feature."
        response = FakeResponse(
            {
                "type": "file",
                "name": "README.md",
                "sha": "sha-sections",
                "content": base64.b64encode(readme.encode()).decode(),
            }
        )
        with patch.dict("os.environ", {"NEXO_PUBLIC_GITHUB_REPOSITORIES": "OMNIX"}, clear=False):
            PublicKnowledgeRefresher(FakeClient(response), db_path=str(self.db)).refresh()
        docs = retrieve_knowledge("Project Features", channel="portfolio_web", scope="public_portfolio", db_path=self.db)
        joined = "\n".join(item["content"] for item in docs)
        self.assertIn("Public description.", joined)
        self.assertIn("Public feature.", joined)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", joined)


if __name__ == "__main__":
    unittest.main()
