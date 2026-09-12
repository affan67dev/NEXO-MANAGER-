from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.memory_engine as memory_engine
import core.semantic_memory as semantic_memory
from core.load_guard import LoadGuard
from tool_registry import execute
import nexo_tools  # noqa: F401 - registers runtime tools


class StabilityTests(unittest.TestCase):
    def test_tool_argument_validation(self):
        result = execute("device_action", {"action": "not_allowed"}, owner=True)
        self.assertEqual(result["error"], "argument_not_allowed")

    def test_tool_owner_boundary(self):
        result = execute("device_action", {"action": "battery"}, owner=False)
        self.assertEqual(result["error"], "owner_required")

    def test_load_guard_is_bounded(self):
        async def scenario():
            guard = LoadGuard(per_user_interval=0, max_active=1, max_queue=1, max_wait=0.05)
            first, _ = await guard.acquire(1)
            second, reason = await guard.acquire(2)
            third, reason3 = await guard.acquire(3)
            await guard.release()
            return first, second, reason, third, reason3

        first, second, reason, third, reason3 = asyncio.run(scenario())
        self.assertTrue(first)
        self.assertTrue(second or reason == "queue_timeout")
        self.assertFalse(third)
        self.assertIn(reason3, {"overloaded", "queue_timeout"})

    def test_memory_is_user_isolated_and_secret_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            old_core = memory_engine.DB
            old_semantic = semantic_memory.DB
            try:
                memory_engine.DB = path
                semantic_memory.DB = path
                self.assertTrue(memory_engine.save_memory("project", "private project alpha", user_id=1))
                self.assertEqual(memory_engine.search_memory("private", user_id=2), [])
                self.assertEqual(memory_engine.search_memory("private", user_id=1)[0][1], "private project alpha")
                self.assertFalse(memory_engine.save_memory("secret", "api_key=abc123", user_id=1))

                store = semantic_memory.SemanticMemory()
                self.assertTrue(store.add("alpha only", user_id=1))
                self.assertEqual(store.search("alpha", user_id=2), [])
                self.assertFalse(store.add("password=abc123", user_id=1))
            finally:
                memory_engine.DB = old_core
                semantic_memory.DB = old_semantic

    def test_planner_does_not_duplicate_user_message(self):
        from agents.executive_planner import ExecutivePlanner

        seen = []
        with patch("agents.executive_planner.LLMRouter.call", side_effect=lambda goal, messages, tools, ask_fn: seen.append(messages) or {"choices": [{"message": {"content": "ok"}}]}):
            answer = ExecutivePlanner("http://llama").run(
                "hello", [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}], [], lambda *a, **k: {}, owner=False
            )
        self.assertEqual(answer, "ok")
        self.assertEqual([m["role"] for m in seen[0]], ["system", "user"])
        self.assertEqual(seen[0][-1]["content"], "hello")


if __name__ == "__main__":
    unittest.main()
