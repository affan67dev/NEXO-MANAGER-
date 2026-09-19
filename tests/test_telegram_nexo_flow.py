import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class FakePlanner:
    def __init__(self, result="Task completed.", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def run(self, goal, messages, tools, executor, **kwargs):
        self.calls.append((goal, messages, tools, kwargs))
        if self.error:
            raise self.error
        return self.result


class TelegramNexoFlowTests(unittest.IsolatedAsyncioTestCase):
    def _update(self, text: str, user_id: int = 123):
        message = SimpleNamespace(text=text, photo=None, document=None, reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()))
        return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=user_id))

    async def _common(self, text, planner):
        import telegram_llama
        update = self._update(text)
        async def fake_heartbeat(_): return None
        async def fake_attachment(*_): return None
        async def fake_acquire(_): return True, "ok"
        async def fake_release(): return None
        with patch.object(telegram_llama.load_guard, "acquire", fake_acquire), patch.object(telegram_llama.load_guard, "release", fake_release), patch.object(telegram_llama, "typing_heartbeat", fake_heartbeat), patch.object(telegram_llama, "handle_attachment", fake_attachment), patch.object(telegram_llama, "planner", planner), patch.object(telegram_llama, "get_or_create_session", return_value="s1"), patch.object(telegram_llama, "recent_turns", return_value=[]), patch.object(telegram_llama.memory, "search", return_value=[]), patch.object(telegram_llama, "save_turn"), patch.object(telegram_llama, "retrieve_knowledge", return_value=[]):
            await telegram_llama.chat(update, SimpleNamespace(), "public")
        return update

    async def test_conversation_reaches_llm_path_without_tools(self):
        planner = FakePlanner(result="Python is a programming language.")
        update = await self._common("Please explain what Python is", planner)
        self.assertEqual(planner.calls[0][2], [])
        self.assertEqual(planner.calls[0][3]["intent"], "conversation")
        update.message.reply_text.assert_awaited_once_with("Python is a programming language.")

    async def test_task_request_gets_tools(self):
        import telegram_llama
        planner = FakePlanner()
        update = self._update("Fix the backend authentication bug")
        async def fake_heartbeat(_): return None
        async def fake_attachment(*_): return None
        async def fake_acquire(_): return True, "ok"
        async def fake_release(): return None
        with patch.object(telegram_llama.load_guard, "acquire", fake_acquire), patch.object(telegram_llama.load_guard, "release", fake_release), patch.object(telegram_llama, "typing_heartbeat", fake_heartbeat), patch.object(telegram_llama, "handle_attachment", fake_attachment), patch.object(telegram_llama, "planner", planner), patch.object(telegram_llama, "get_or_create_session", return_value="s1"), patch.object(telegram_llama, "recent_turns", return_value=[]), patch.object(telegram_llama.memory, "search", return_value=[]), patch.object(telegram_llama, "save_turn"), patch.object(telegram_llama, "schemas", return_value=[{"type": "function", "function": {"name": "test"}}]), patch.object(telegram_llama, "retrieve_knowledge", return_value=[]):
            await telegram_llama.chat(update, SimpleNamespace())
        self.assertEqual(planner.calls[0][3]["intent"], "coding")
        self.assertTrue(planner.calls[0][2])

    async def test_unsafe_input_never_reaches_model(self):
        planner = FakePlanner(result="unsafe")
        update = await self._common("api_key=SECRET1234567890", planner)
        self.assertEqual(planner.calls, [])
        self.assertIn("restricted", update.message.reply_text.await_args.args[0])

    async def test_model_failure_is_isolated_to_one_clean_message(self):
        planner = FakePlanner(error=RuntimeError("llm_provider_unavailable"))
        update = await self._common("Explain why this failed", planner)
        self.assertEqual(update.message.reply_text.await_args.args[0], "NEXO couldn't complete that request right now. The error has been logged.")
        self.assertEqual(update.message.reply_text.await_count, 1)


if __name__ == "__main__":
    unittest.main()
