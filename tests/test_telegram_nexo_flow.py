import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class TelegramNexoFlowTests(unittest.IsolatedAsyncioTestCase):
    def _update(self, text: str, user_id: int = 123):
        message = SimpleNamespace(text=text, photo=None, document=None, reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()))
        return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=user_id))

    async def test_conversation_reaches_llm_path_without_tools(self):
        import telegram_llama
        update = self._update("Please explain what Python is")
        calls = []
        async def fake_heartbeat(_): return None
        async def fake_attachment(*_): return None
        async def fake_acquire(_): return True, "ok"
        async def fake_release(): return None
        def fake_run(goal, messages, tools, executor, **kwargs):
            calls.append((goal, tools, kwargs.get("intent")))
            return "Python is a programming language."
        with patch.object(telegram_llama.load_guard, "acquire", fake_acquire), patch.object(telegram_llama.load_guard, "release", fake_release), patch.object(telegram_llama, "typing_heartbeat", fake_heartbeat), patch.object(telegram_llama, "handle_attachment", fake_attachment), patch.object(telegram_llama.planner, "run", fake_run), patch.object(telegram_llama, "get_or_create_session", return_value="s1"), patch.object(telegram_llama, "recent_turns", return_value=[]), patch.object(telegram_llama.memory, "search", return_value=[]), patch.object(telegram_llama, "save_turn"):
            await telegram_llama.chat(update, SimpleNamespace())
        self.assertEqual(calls, [("Please explain what Python is", [], "conversation")])
        update.message.reply_text.assert_awaited_once_with("Python is a programming language.")

    async def test_task_request_gets_tools(self):
        import telegram_llama
        update = self._update("Fix the backend authentication bug")
        calls = []
        async def fake_heartbeat(_): return None
        async def fake_attachment(*_): return None
        async def fake_acquire(_): return True, "ok"
        async def fake_release(): return None
        def fake_run(goal, messages, tools, executor, **kwargs):
            calls.append((goal, tools, kwargs.get("intent")))
            return "Task completed."
        with patch.object(telegram_llama.load_guard, "acquire", fake_acquire), patch.object(telegram_llama.load_guard, "release", fake_release), patch.object(telegram_llama, "typing_heartbeat", fake_heartbeat), patch.object(telegram_llama, "handle_attachment", fake_attachment), patch.object(telegram_llama.planner, "run", fake_run), patch.object(telegram_llama, "get_or_create_session", return_value="s1"), patch.object(telegram_llama, "recent_turns", return_value=[]), patch.object(telegram_llama.memory, "search", return_value=[]), patch.object(telegram_llama, "save_turn"), patch.object(telegram_llama, "schemas", return_value=[{"type": "function", "function": {"name": "test"}}]):
            await telegram_llama.chat(update, SimpleNamespace())
        self.assertEqual(calls[0][2], "coding")
        self.assertTrue(calls[0][1])

    async def test_unsafe_input_never_reaches_model(self):
        import telegram_llama
        update = self._update("api_key=SECRET1234567890")
        model_calls = []
        async def fake_heartbeat(_): return None
        async def fake_attachment(*_): return None
        async def fake_acquire(_): return True, "ok"
        async def fake_release(): return None
        def fake_run(*args, **kwargs): model_calls.append(True); return "unsafe"
        with patch.object(telegram_llama.load_guard, "acquire", fake_acquire), patch.object(telegram_llama.load_guard, "release", fake_release), patch.object(telegram_llama, "typing_heartbeat", fake_heartbeat), patch.object(telegram_llama, "handle_attachment", fake_attachment), patch.object(telegram_llama.planner, "run", fake_run):
            await telegram_llama.chat(update, SimpleNamespace())
        self.assertEqual(model_calls, [])
        self.assertIn("restricted", update.message.reply_text.await_args.args[0])

    async def test_model_failure_is_isolated_to_one_clean_message(self):
        import telegram_llama
        update = self._update("Explain why this failed")
        async def fake_heartbeat(_): return None
        async def fake_attachment(*_): return None
        async def fake_acquire(_): return True, "ok"
        async def fake_release(): return None
        with patch.object(telegram_llama.load_guard, "acquire", fake_acquire), patch.object(telegram_llama.load_guard, "release", fake_release), patch.object(telegram_llama, "typing_heartbeat", fake_heartbeat), patch.object(telegram_llama.planner, "run", side_effect=RuntimeError("qwen_request_failed")), patch.object(telegram_llama, "get_or_create_session", return_value="s1"), patch.object(telegram_llama, "recent_turns", return_value=[]), patch.object(telegram_llama.memory, "search", return_value=[]):
            await telegram_llama.chat(update, SimpleNamespace())
        self.assertEqual(update.message.reply_text.await_args.args[0], "NEXO couldn't complete that request right now. The error has been logged.")
        self.assertEqual(update.message.reply_text.await_count, 1)


if __name__ == "__main__":
    unittest.main()
