import os
import unittest
from unittest.mock import patch

from agents.executive_planner import ExecutivePlanner
from services.llm_router import LLMRouter


class LLMStabilityTests(unittest.TestCase):
    def env(self, **extra):
        values = {"NEXO_LLM_RETRIES": "1", "NEXO_LLM_BACKOFF_SECONDS": "0", "NEXO_QWEN_CONTEXT_TOKENS": "1024", "NEXO_QWEN_OUTPUT_TOKENS": "256"}
        values.update(extra)
        return patch.dict(os.environ, values, clear=False)

    @staticmethod
    def success(model):
        return {"choices": [{"message": {"role": "assistant", "content": f"answer from {model}"}}]}

    def test_all_requests_use_qwen(self):
        with self.env():
            router = LLMRouter("http://qwen")
            calls = []
            for request in ("hello", "analyze this deeply", "compare architecture tradeoffs"):
                router.call(request, [{"role": "user", "content": request}], None, lambda url, *_: calls.append(url) or self.success(url))
            self.assertEqual(calls, ["http://qwen", "http://qwen", "http://qwen"])

    def test_qwen_timeout_is_not_routed_to_another_model(self):
        with self.env(NEXO_LLM_RETRIES="1"):
            router = LLMRouter("http://qwen")
            calls = []
            def fake(url, *_):
                calls.append(url)
                raise TimeoutError("timeout")
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("analyze this deeply", [{"role": "user", "content": "analyze this deeply"}], None, fake)
            self.assertEqual(calls, ["http://qwen", "http://qwen"])

    def test_http_failure_is_safe_and_does_not_expose_backend_detail(self):
        with self.env(NEXO_LLM_RETRIES="0"):
            router = LLMRouter("http://qwen")
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed") as caught:
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 500 secret-token")))
            self.assertNotIn("secret-token", str(caught.exception))

    def test_empty_response_is_rejected(self):
        with self.env(NEXO_LLM_RETRIES="0"):
            router = LLMRouter("http://qwen")
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: {"choices": [{"message": {"content": ""}}]})

    def test_malformed_response_is_rejected(self):
        with self.env(NEXO_LLM_RETRIES="0"):
            router = LLMRouter("http://qwen")
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: {"unexpected": "shape"})

    def test_qwen_not_configured_is_explicit(self):
        router = LLMRouter("")
        with self.assertRaisesRegex(RuntimeError, "qwen_endpoint_not_configured"):
            router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: self.success("qwen"))

    def test_planner_rejects_empty_final_answer(self):
        planner = ExecutivePlanner("http://qwen")
        with patch.object(planner.router, "call", return_value={"choices": [{"message": {"content": ""}}]}), patch("services.context_budget.count_input_tokens", return_value=20):
            with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
                planner.run("hello", [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}], [], lambda *a, **k: {}, owner=True)

    def test_tool_retry_path_does_not_repeat_completed_action(self):
        planner = ExecutivePlanner("http://qwen")
        calls = []
        responses = [
            {"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "do_action", "arguments": "{\"x\":1}"}}]}}]},
            {"choices": [{"message": {"tool_calls": [{"id": "2", "function": {"name": "do_action", "arguments": "{\"x\":1}"}}]}}]},
            {"choices": [{"message": {"content": "Action already completed."}}]},
        ]
        with patch.object(planner.router, "call", side_effect=responses), patch("services.context_budget.count_input_tokens", return_value=20):
            result = planner.run("do the action", [{"role": "system", "content": "system"}, {"role": "user", "content": "do the action"}], [{}], lambda *a, **k: calls.append(1) or {"ok": True}, owner=True, max_steps=3)
        self.assertEqual(calls, [1])
        self.assertEqual(result, "Action already completed.")


if __name__ == "__main__":
    unittest.main()
