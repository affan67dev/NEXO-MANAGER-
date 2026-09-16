from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class FakePlanner:
    def __init__(self, result="answer"):
        self.result = result
        self.calls = []

    def run(self, goal, messages, tools, executor, **kwargs):
        self.calls.append((goal, messages, tools, kwargs))
        return self.result


class TelegramConversationTests(unittest.TestCase):
    def test_hello_uses_fast_path_without_model_call(self):
        import telegram_llama
        reply_text = AsyncMock()
        update = SimpleNamespace(message=SimpleNamespace(text="Hello", reply_text=reply_text), effective_user=SimpleNamespace(id=123))
        fake_planner = FakePlanner()

        async def fake_typing(_update):
            return None

        async def scenario():
            with patch.object(telegram_llama.load_guard, "acquire", new=AsyncMock(return_value=(True, ""))), \
                 patch.object(telegram_llama.load_guard, "release", new=AsyncMock()), \
                 patch.object(telegram_llama, "typing_heartbeat", new=fake_typing), \
                 patch.object(telegram_llama, "handle_attachment", new=AsyncMock(return_value=None)), \
                 patch.object(telegram_llama, "planner", fake_planner):
                await telegram_llama.chat(update, SimpleNamespace())
        asyncio.run(scenario())
        self.assertEqual(fake_planner.calls, [])
        self.assertEqual(reply_text.await_args.args[0], "Hello! How can I help?")

    def test_hello_is_conversation_not_out_of_scope(self):
        from agents.manager.manager import NexoManager
        task = NexoManager().create_task("Hello")
        self.assertEqual(task.intent, "conversation")
        self.assertEqual(task.agent, "manager")


if __name__ == "__main__":
    unittest.main()
