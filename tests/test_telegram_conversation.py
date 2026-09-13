from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class TelegramConversationTests(unittest.TestCase):
    def test_hello_uses_nexo_conversation_path_without_tools(self):
        import telegram_llama

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(text="Hello", reply_text=reply_text),
            effective_user=SimpleNamespace(id=123),
        )

        async def fake_typing(_update):
            return None

        async def scenario():
            with patch.object(telegram_llama.load_guard, "acquire", new=AsyncMock(return_value=(True, ""))), \
                 patch.object(telegram_llama.load_guard, "release", new=AsyncMock()), \
                 patch.object(telegram_llama, "typing_heartbeat", new=fake_typing), \
                 patch.object(telegram_llama, "handle_attachment", new=AsyncMock(return_value=None)), \
                 patch.object(telegram_llama, "get_or_create_session", return_value="session-123"), \
                 patch.object(telegram_llama, "recent_turns", return_value=[]), \
                 patch.object(telegram_llama.memory, "search", return_value=[]), \
                 patch.object(telegram_llama, "save_turn", return_value=True), \
                 patch.object(telegram_llama.planner, "run", return_value="Hello! How can I help you?") as run:
                await telegram_llama.chat(update, SimpleNamespace())
                return run

        run = asyncio.run(scenario())
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0], "Hello")
        self.assertEqual(args[2], [])
        self.assertEqual(kwargs["max_steps"], 1)
        self.assertEqual(reply_text.await_args_list[0].args[0], "Hello! How can I help you?")
        self.assertNotIn("Sorry, I couldn't complete that request right now.", [c.args[0] for c in reply_text.await_args_list])

    def test_hello_is_conversation_not_out_of_scope(self):
        from agents.manager.manager import NexoManager

        task = NexoManager().create_task("Hello")
        self.assertEqual(task.intent, "conversation")
        self.assertEqual(task.agent, "manager")


if __name__ == "__main__":
    unittest.main()
