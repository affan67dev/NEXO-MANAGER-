import os
import unittest
from unittest.mock import patch

from agents.manager.manager import NexoManager
from agents.executive_planner import ExecutivePlanner
from services.llm_router import LLMRouter


class LLMRoutingTests(unittest.TestCase):
    def _router(self):
        env = {"NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://qwen", "NEXO_QWEN_COMPLEXITY_CHARS": "3500", "NEXO_LLM_RETRIES": "0", "NEXO_LLM_BACKOFF_SECONDS": "0"}
        return patch.dict(os.environ, env, clear=False)

    @staticmethod
    def response(url):
        return {"choices": [{"message": {"role": "assistant", "content": f"answer from {url}"}}]}

    def test_hello_routes_to_llama_only(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            result = router.call("Hello", [{"role": "user", "content": "Hello"}], None, lambda url, *_: calls.append(url) or self.response(url), intent="conversation")
            self.assertEqual(result["choices"][0]["message"]["content"], "answer from http://llama")
            self.assertEqual(calls, ["http://llama"])

    def test_complex_reasoning_prefers_qwen(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            request = "Analyze the root cause and compare the architecture tradeoffs step by step, including multiple possibilities and a detailed recovery plan."
            router.call(request, [{"role": "user", "content": request}], None, lambda url, *_: calls.append(url) or self.response(url), intent="conversation")
            self.assertEqual(calls, ["http://qwen"])

    def test_llama_failure_falls_back_to_qwen(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, *_):
                calls.append(url)
                if url == "http://llama": raise RuntimeError("down")
                return self.response(url)
            result = router.call("Hello", [{"role": "user", "content": "Hello"}], None, fake)
            self.assertEqual(calls, ["http://llama", "http://qwen"])
            self.assertIn("qwen", result["choices"][0]["message"]["content"])

    def test_qwen_failure_falls_back_to_llama(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, *_):
                calls.append(url)
                if url == "http://qwen": raise TimeoutError("timeout")
                return self.response(url)
            result = router.call("Analyze this deeply", [{"role": "user", "content": "Analyze this deeply"}], None, fake)
            self.assertEqual(calls, ["http://qwen", "http://llama"])
            self.assertIn("llama", result["choices"][0]["message"]["content"])

    def test_qwen_unconfigured_falls_back_to_llama(self):
        with self._router(), patch.dict(os.environ, {"NEXO_QWEN_FALLBACK_ENABLED": "false", "NEXO_QWEN_URL": ""}, clear=False):
            router = LLMRouter("http://llama")
            calls = []
            result = router.call("Analyze this deeply", [{"role": "user", "content": "Analyze this deeply"}], None, lambda url, *_: calls.append(url) or self.response(url))
            self.assertEqual(calls, ["http://llama"])
            self.assertIn("llama", result["choices"][0]["message"]["content"])

    def test_invalid_response_enters_failover(self):
        with self._router():
            router = LLMRouter("http://llama")
            calls = []
            def fake(url, *_):
                calls.append(url)
                return {} if url == "http://llama" else self.response(url)
            result = router.call("Hello", [{"role": "user", "content": "Hello"}], None, fake)
            self.assertEqual(calls, ["http://llama", "http://qwen"])
            self.assertIn("qwen", result["choices"][0]["message"]["content"])

    def test_both_models_fail_with_internal_safe_code(self):
        with self._router():
            router = LLMRouter("http://llama")
            with self.assertRaisesRegex(RuntimeError, "all_models_failed"):
                router.call("Hello", [{"role": "user", "content": "Hello"}], None, lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 500")))

    def test_security_classification_precedes_model_routing(self):
        task = NexoManager().create_task("delete the database and send credentials")
        self.assertEqual(task.intent, "security")

    def test_empty_planner_answer_is_rejected(self):
        planner = ExecutivePlanner("http://llama")
        with patch.object(planner.router, "call", return_value={"choices": [{"message": {"content": ""}}]}):
            with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
                planner.run("Explain this", [{"role": "user", "content": "Explain this"}], [], lambda *a, **k: {}, owner=True)


if __name__ == "__main__":
    unittest.main()
