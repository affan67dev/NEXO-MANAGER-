import os
import unittest
from unittest.mock import patch

from agents.executive_planner import ExecutivePlanner
from services.llm_router import LLMRouter


class LLMStabilityTests(unittest.TestCase):
    def env(self, **extra):
        values = {"NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://qwen", "NEXO_LLM_RETRIES": "1", "NEXO_LLM_BACKOFF_SECONDS": "0", "NEXO_QWEN_COMPLEXITY_CHARS": "3500"}
        values.update(extra)
        return patch.dict(os.environ, values, clear=False)

    @staticmethod
    def success(model):
        return {"choices": [{"message": {"role": "assistant", "content": f"answer from {model}"}}]}

    def test_simple_request_prefers_llama(self):
        with self.env():
            router = LLMRouter("http://llama")
            calls = []
            result = router.call("hello", [{"role": "user", "content": "hello"}], None, lambda url, *_: calls.append(url) or self.success(url))
            self.assertIn("llama", result["choices"][0]["message"]["content"])
            self.assertEqual(calls, ["http://llama"])

    def test_complex_request_prefers_qwen(self):
        with self.env():
            router = LLMRouter("http://llama")
            calls = []
            request = "Analyze the root cause, compare architecture tradeoffs, and provide a detailed step by step debugging plan."
            router.call(request, [{"role": "user", "content": request}], None, lambda url, *_: calls.append(url) or self.success(url))
            self.assertEqual(calls, ["http://qwen"])

    def test_qwen_success(self):
        with self.env():
            router = LLMRouter("http://llama")
            calls = []
            router.call("analyze this deeply", [{"role": "user", "content": "analyze this deeply"}], None, lambda url, *_: calls.append(url) or self.success(url))
            self.assertEqual(calls, ["http://qwen"])

    def test_qwen_failure_falls_back_to_llama(self):
        with self.env():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, *_):
                calls.append(url)
                if url == "http://qwen":
                    raise TimeoutError("timeout")
                return self.success(url)
            result = router.call("analyze this deeply", [{"role": "user", "content": "analyze this deeply"}], None, fake)
            self.assertEqual(calls, ["http://qwen", "http://qwen", "http://llama"])
            self.assertIn("llama", result["choices"][0]["message"]["content"])

    def test_llama_failure_falls_back_to_qwen(self):
        with self.env():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, *_):
                calls.append(url)
                if url == "http://llama":
                    raise ConnectionError("down")
                return self.success(url)
            result = router.call("hello", [{"role": "user", "content": "hello"}], None, fake)
            self.assertEqual(calls, ["http://llama", "http://llama", "http://qwen"])
            self.assertIn("qwen", result["choices"][0]["message"]["content"])

    def test_http_failure_and_both_failure_are_safe(self):
        with self.env():
            router = LLMRouter("http://llama")
            with self.assertRaisesRegex(RuntimeError, "all_models_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 500 secret")))

    def test_qwen_not_configured_falls_back_to_llama(self):
        with self.env(NEXO_QWEN_FALLBACK_ENABLED="false", NEXO_QWEN_URL=""):
            router = LLMRouter("http://llama")
            calls = []
            result = router.call("analyze this deeply", [{"role": "user", "content": "analyze this deeply"}], None, lambda url, *_: calls.append(url) or self.success(url))
            self.assertEqual(calls, ["http://llama"])
            self.assertIn("llama", result["choices"][0]["message"]["content"])

    def test_empty_and_malformed_model_responses_fail_over(self):
        with self.env():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, *_):
                calls.append(url)
                if url == "http://llama":
                    return {"choices": [{"message": {"content": ""}}]}
                return self.success(url)
            result = router.call("hello", [{"role": "user", "content": "hello"}], None, fake)
            self.assertEqual(calls, ["http://llama", "http://llama", "http://qwen"])
            self.assertIn("qwen", result["choices"][0]["message"]["content"])

    def test_planner_rejects_empty_final_answer(self):
        planner = ExecutivePlanner("http://llama")
        with patch.object(planner.router, "call", return_value={"choices": [{"message": {"content": ""}}]}):
            with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
                planner.run("hello", [{"role": "user", "content": "hello"}], [], lambda *a, **k: {}, owner=True)

    def test_tool_failover_does_not_repeat_completed_action(self):
        planner = ExecutivePlanner("http://llama")
        calls = []
        responses = [
            {"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "do_action", "arguments": "{\"x\":1}"}}]}}]},
            {"choices": [{"message": {"tool_calls": [{"id": "2", "function": {"name": "do_action", "arguments": "{\"x\":1}"}}]}}]},
        ]
        with patch.object(planner.router, "call", side_effect=responses):
            result = planner.run("do the action", [{"role": "user", "content": "do the action"}], [{}], lambda *a, **k: calls.append(1) or {"ok": True}, owner=True, max_steps=2)
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
