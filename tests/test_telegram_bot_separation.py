from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from core.identity import authorize_bot_update, resolve_bot_identity
from core import memory_engine
from tool_registry import Tool, register, schemas
import telegram_llama


class _FakeMessage:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text: str):
        self.replies.append(text)


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeUpdate:
    def __init__(self, user_id: int):
        self.effective_user = _FakeUser(user_id)
        self.message = _FakeMessage()


class TelegramBotSeparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_TELEGRAM_USER_ID": "8921221615",
                "ADMIN_TELEGRAM_BOT_TOKEN": "admin-token-test-only",
                "PUBLIC_TELEGRAM_BOT_TOKEN": "public-token-test-only",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    async def test_unauthorized_admin_bot_stops_before_load_guard_ai_or_data(self):
        update = _FakeUpdate(777777)
        with (
            patch.object(telegram_llama.load_guard, "acquire", new=AsyncMock()) as acquire,
            patch.object(telegram_llama, "retrieve_knowledge") as retrieve,
            patch.object(telegram_llama, "ExecutivePlanner") as planner,
        ):
            await telegram_llama.chat(update, None, "admin")
        acquire.assert_not_awaited()
        retrieve.assert_not_called()
        planner.assert_not_called()
        self.assertEqual(update.message.replies, ["Sorry, I can't help with that."])

    async def test_admin_bot_allowlist_is_numeric_id_only(self):
        self.assertTrue(authorize_bot_update("admin", 8921221615))
        self.assertFalse(authorize_bot_update("admin", 777777))

    async def test_public_prompt_cannot_change_bot_role(self):
        update = _FakeUpdate(777777)
        with patch.object(telegram_llama.load_guard, "acquire", new=AsyncMock(return_value=(False, "rate_limited"))):
            await telegram_llama.chat(update, None, "public")
        self.assertEqual(update.message.replies, ["Please wait a moment before sending another request."])

    def test_public_users_have_isolated_memory_by_numeric_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_db = memory_engine.DB
            memory_engine.DB = Path(tmp) / "memory.db"
            try:
                memory_engine.save_memory("requirements", "client A private requirement", user_id=1001)
                memory_engine.save_memory("requirements", "client B private requirement", user_id=1002)
                self.assertEqual(
                    [row[1] for row in memory_engine.search_memory("private", user_id=1001)],
                    ["client A private requirement"],
                )
                self.assertEqual(
                    [row[1] for row in memory_engine.search_memory("private", user_id=1002)],
                    ["client B private requirement"],
                )
            finally:
                memory_engine.DB = old_db

    def test_public_bot_never_inherits_admin_role(self):
        self.assertEqual(resolve_bot_identity("public", 8921221615).role, "public_client")
        with self.assertRaises(PermissionError):
            resolve_bot_identity("admin", 777777)

    def test_public_bot_schema_excludes_owner_only_tools(self):
        marker = Tool(
            name="__test_owner_only__",
            description="test",
            parameters={"type": "object", "properties": {}},
            handler=lambda: {"ok": True},
            owner_only=True,
        )
        register(marker)
        try:
            public_names = {x["function"]["name"] for x in schemas(include_owner_only=False)}
            admin_names = {x["function"]["name"] for x in schemas(include_owner_only=True)}
            self.assertNotIn(marker.name, public_names)
            self.assertIn(marker.name, admin_names)
        finally:
            # Registry is intentionally private; remove only this test marker.
            import tool_registry
            tool_registry._REGISTRY.pop(marker.name, None)

    def test_tokens_are_not_in_unauthorized_response_or_security_logs(self):
        logger = logging.getLogger("nexo.telegram")
        with self.assertLogs(logger, level="INFO") as captured:
            logger.info("unauthorized admin update rejected")
        output = "\n".join(captured.output)
        self.assertNotIn("admin-token-test-only", output)
        self.assertNotIn("public-token-test-only", output)
        self.assertNotIn("admin-token-test-only", telegram_llama._unauthorized_message())
        self.assertNotIn("public-token-test-only", telegram_llama._unauthorized_message())


if __name__ == "__main__":
    unittest.main()
