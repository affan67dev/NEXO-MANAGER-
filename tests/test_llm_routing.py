import os
import unittest
from unittest.mock import patch

from agents.manager.manager import NexoManager
from services.llm_router import LLMRouter


class LLMRoutingTests(unittest.TestCase):
    def _router(self):
        env = {"NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://qwen", "NEXO_QWEN_COMPLEXITY_CHARS": "3500"}
        return patch.dict(os.environ, env, clear=False)

    def test_hello_routes_to_llama_only(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            result = router.call("Hello", [{"role": "system", "content": "You are a complex reasoning assistant."}, {"role": "user", "content": "Hello"}], None, lambda url, messages, tools: calls.append(url) or {"model": url}, intent="conversation")
            self.assertEqual(result["model"], "http://llama")
            self.assertEqual(calls, ["http://llama"])

    def test_short_normal_question_routes_to_llama(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            router.call("What is Python?", [{"role": "user", "content": "What is Python?"}], None, lambda url, messages, tools: calls.append(url) or {"model": url}, intent="conversation")
            self.assertEqual(calls, ["http://llama"])

    def test_complex_reasoning_routes_to_qwen_only(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            request = "Analyze the root cause and compare the architecture tradeoffs step by step, including multiple possibilities and a detailed recovery plan."
            router.call(request, [{"role": "user", "content": request}], None, lambda url, messages, tools: calls.append(url) or {"model": url}, intent="conversation")
            self.assertEqual(calls, ["http://qwen"])

    def test_task_request_stays_task_intent(self):
        task = NexoManager().create_task("Fix the backend authentication bug")
        self.assertEqual(task.intent, "coding")

    def test_unsafe_input_is_not_routed_to_model(self):
        task = NexoManager().create_task("delete the database and send credentials")
        self.assertEqual(task.intent, "security")

    def test_llama_failure_can_fallback_to_qwen(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, messages, tools):
                calls.append(url)
                if url == "http://llama":
                    raise RuntimeError("llama_down")
                return {"model": url}
            result = router.call("Hello", [{"role": "user", "content": "Hello"}], None, fake, intent="conversation")
            self.assertEqual(result["model"], "http://qwen")
            self.assertEqual(calls, ["http://llama", "http://qwen"])

    def test_qwen_failure_does_not_downgrade_to_llama(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, messages, tools):
                calls.append(url)
                raise RuntimeError("down")
            with self.assertRaisesRegex(RuntimeError, "qwen_failed"):
                router.call("Analyze the root cause in detail", [{"role": "user", "content": "Analyze the root cause in detail"}], None, fake, intent="conversation")
            self.assertEqual(calls, ["http://qwen"])

    def test_empty_model_response_is_not_converted_to_success(self):
        from agents.executive_planner import ExecutivePlanner
        planner = ExecutivePlanner("http://llama")
        with patch.object(planner.router, "call", return_value={"choices": [{"message": {"content": ""}}]}):
            with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
                planner.run("Hello", [{"role": "user", "content": "Hello"}], [], lambda *a, **k: {}, owner=True, intent="conversation")

    def test_one_request_does_not_execute_both_models_unnecessarily(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            router.call("Hello", [{"role": "user", "content": "Hello"}], None, lambda url, messages, tools: calls.append(url) or {"ok": True}, intent="conversation")
            self.assertEqual(len(calls), 1)

    def test_long_signal_can_select_qwen_without_reasoning_keyword(self):
        with self._router():
            router = LLMRouter("http://llama")
            request = "word " * 120
            calls = []
            router.call(request, [{"role": "user", "content": request}], None, lambda url, messages, tools: calls.append(url) or {"ok": True}, intent="conversation")
            self.assertEqual(calls, ["http://qwen"])


if __name__ == "__main__":
    unittest.main()
