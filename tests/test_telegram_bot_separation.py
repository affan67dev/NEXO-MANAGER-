from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.identity import resolve_bot_identity
from tool_registry import Tool, register, schemas


class TelegramBotSeparationTests(unittest.IsolatedAsyncioTestCase):
    def test_public_bot_isolation_for_admin_id(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            self.assertEqual(resolve_bot_identity("public", 8921221615).role, "public_client")

    async def test_unauthorized_admin_is_rejected_before_load_guard_and_ai(self):
        import telegram_llama

        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=AsyncMock()),
            effective_user=SimpleNamespace(id=999999),
        )
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False),              patch.object(telegram_llama.load_guard, "acquire", new=AsyncMock(side_effect=AssertionError("load guard must not run"))),              patch.object(telegram_llama, "retrieve_knowledge", side_effect=AssertionError("knowledge must not run")),              patch.object(telegram_llama, "ExecutivePlanner", side_effect=AssertionError("AI must not run")):
            await telegram_llama.chat(update, SimpleNamespace(), bot_role="admin")
        update.message.reply_text.assert_awaited_once_with("Sorry, I can't help with that.")

    async def test_public_bot_reaches_public_path_for_admin_id(self):
        import telegram_llama

        update = SimpleNamespace(
            message=SimpleNamespace(text="Hello", photo=None, document=None, reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock())),
            effective_user=SimpleNamespace(id=8921221615),
        )
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False),              patch.object(telegram_llama.load_guard, "acquire", new=AsyncMock(return_value=(True, "ok"))),              patch.object(telegram_llama.load_guard, "release", new=AsyncMock()),              patch.object(telegram_llama, "typing_heartbeat", new=AsyncMock()),              patch.object(telegram_llama, "handle_attachment", new=AsyncMock(return_value=None)),              patch.object(telegram_llama, "get_or_create_session", return_value="s1"),              patch.object(telegram_llama, "save_turn"),              patch.object(telegram_llama, "planner", None),              patch.object(telegram_llama, "ExecutivePlanner") as planner_cls:
            fake = planner_cls.return_value
            fake.run.return_value = "hello"
            await telegram_llama.chat(update, SimpleNamespace(), bot_role="public")
        self.assertTrue(update.message.reply_text.await_count)

    def test_owner_only_tools_are_hidden_from_public_schema(self):
        register(Tool("test_owner_only", "owner", {"type": "object", "properties": {}}, lambda: {"ok": True}, owner_only=True))
        register(Tool("test_public_tool", "public", {"type": "object", "properties": {}}, lambda: {"ok": True}, owner_only=False))
        public_names = {item["function"]["name"] for item in schemas(include_owner_only=False)}
        admin_names = {item["function"]["name"] for item in schemas(include_owner_only=True)}
        self.assertNotIn("test_owner_only", public_names)
        self.assertIn("test_public_tool", public_names)
        self.assertIn("test_owner_only", admin_names)


if __name__ == "__main__":
    unittest.main()
