import os
import unittest
from unittest.mock import patch

from agents.executive_planner import ExecutivePlanner
from services.llm_router import LLMRouter


class FakeProvider:
    name = "openrouter"
    model = "test/model"

    def __init__(self, result=None, error=None):
        self.result = result or {"choices": [{"message": {"role": "assistant", "content": "answer"}}]}
        self.error = error
        class Config:
            output_tokens = 512
        self.config = Config()

    def complete(self, messages, tools=None, max_tokens=256):
        if self.error:
            raise self.error
        return self.result


class LLMStabilityTests(unittest.TestCase):
    def test_all_requests_use_configured_hosted_provider(self):
        provider = FakeProvider()
        router = LLMRouter(provider)
        for request in ("hello", "analyze this deeply", "compare architecture tradeoffs"):
            result = router.call(request, [{"role": "user", "content": request}])
            self.assertEqual(result["choices"][0]["message"]["content"], "answer")
        self.assertEqual(router.choose_model("hi", []), "test/model")

    def test_hosted_timeout_is_not_routed_to_another_model(self):
        provider = FakeProvider(error=RuntimeError("llm_provider_timeout"))
        router = LLMRouter(provider)
        with self.assertRaisesRegex(RuntimeError, "llm_provider_timeout"):
            router.call("analyze this deeply", [{"role": "user", "content": "analyze this deeply"}])

    def test_provider_failure_is_safe_and_does_not_expose_backend_detail(self):
        provider = FakeProvider(error=RuntimeError("llm_provider_unavailable"))
        router = LLMRouter(provider)
        with self.assertRaisesRegex(RuntimeError, "llm_provider_unavailable") as caught:
            router.call("hello", [{"role": "user", "content": "hello"}])
        self.assertNotIn("secret-token", str(caught.exception))

    def test_empty_response_is_rejected_by_planner(self):
        provider = FakeProvider({"choices": [{"message": {"content": ""}}]})
        planner = ExecutivePlanner(provider)
        with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
            planner.run("hello", [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}], [], lambda *a, **k: {}, owner=True)

    def test_missing_hosted_configuration_is_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "llm_provider_not_configured"):
                LLMRouter()

    def test_planner_rejects_empty_final_answer(self):
        provider = FakeProvider({"choices": [{"message": {"content": ""}}]})
        planner = ExecutivePlanner(provider)
        with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
            planner.run("hello", [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}], [], lambda *a, **k: {}, owner=True)

    def test_tool_retry_path_does_not_repeat_completed_action(self):
        provider = FakeProvider()
        planner = ExecutivePlanner(provider)
        calls = []
        responses = [
            {"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "do_action", "arguments": "{\"x\":1}"}}]}}]},
            {"choices": [{"message": {"tool_calls": [{"id": "2", "function": {"name": "do_action", "arguments": "{\"x\":1}"}}]}}]},
            {"choices": [{"message": {"content": "Action already completed."}}]},
        ]
        with patch.object(planner.router, "call", side_effect=responses):
            result = planner.run("do the action", [{"role": "system", "content": "system"}, {"role": "user", "content": "do the action"}], [{}], lambda *a, **k: calls.append(1) or {"ok": True}, owner=True, max_steps=3)
        self.assertEqual(calls, [1])
        self.assertEqual(result, "Action already completed.")


if __name__ == "__main__":
    unittest.main()
