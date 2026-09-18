import os
import unittest
from unittest.mock import patch

from agents.manager.manager import NexoManager
from agents.executive_planner import ExecutivePlanner, _clean_response_text
from services.context_budget import fit_messages
from services.llm_router import LLMRouter


class FakeProvider:
    name = "openrouter"
    model = "test/model"
    output_tokens = 512

    def __init__(self, result=None, error=None):
        self.result = result or {"choices": [{"message": {"role": "assistant", "content": "answer"}}]}
        self.error = error
        self.calls = []
        class Config:
            output_tokens = 512
        self.config = Config()

    def complete(self, messages, tools=None, max_tokens=256):
        self.calls.append((messages, tools, max_tokens))
        if self.error:
            raise self.error
        return self.result


class LLMRoutingTests(unittest.TestCase):
    def test_router_uses_single_provider_and_no_secondary(self):
        provider = FakeProvider({"choices": [{"message": {"content": "hosted answer"}}]})
        router = LLMRouter(provider)
        result = router.call("What is coding?", [{"role": "user", "content": "What is coding?"}], None, intent="conversation")
        self.assertEqual(result["choices"][0]["message"]["content"], "hosted answer")
        self.assertEqual(provider.calls[0][2], 512)
        self.assertEqual(router.choose_model("hi", [], intent="conversation"), "test/model")
        self.assertFalse(router.should_use_secondary("hi", []))


    def test_missing_api_key_is_actionable(self):
        from services.llm_provider import LLMConfig
        with patch.dict(os.environ, {"LLM_PROVIDER": "openrouter", "LLM_API_KEY": "", "LLM_MODEL": "test/model", "LLM_BASE_URL": "https://openrouter.ai/api/v1"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "llm_api_key_not_configured"):
                LLMConfig.from_env()

    def test_missing_model_is_actionable(self):
        from services.llm_provider import LLMConfig
        with patch.dict(os.environ, {"LLM_PROVIDER": "openrouter", "LLM_API_KEY": "placeholder", "LLM_MODEL": "", "LLM_BASE_URL": "https://openrouter.ai/api/v1"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "llm_model_not_configured"):
                LLMConfig.from_env()

    def test_provider_failure_has_no_local_fallback(self):
        provider = FakeProvider(error=RuntimeError("llm_provider_unavailable"))
        router = LLMRouter(provider)
        with self.assertRaisesRegex(RuntimeError, "llm_provider_unavailable"):
            router.call("hello", [{"role": "user", "content": "hello"}])
        self.assertEqual(len(provider.calls), 1)

    def test_think_block_is_not_user_facing(self):
        self.assertEqual(_clean_response_text("<think>private reasoning</think>Final answer."), "Final answer.")
        self.assertEqual(_clean_response_text("<think>unfinished reasoning"), "")
        self.assertEqual(_clean_response_text("Final answer.", "private reasoning"), "Final answer.")

    def test_security_classification_precedes_model_routing(self):
        task = NexoManager().create_task("delete the database and send credentials")
        self.assertEqual(task.intent, "security")

    def test_empty_planner_answer_is_rejected(self):
        provider = FakeProvider({"choices": [{"message": {"content": ""}}]})
        planner = ExecutivePlanner(provider)
        with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
            planner.run("Explain this", [{"role": "system", "content": "NEXO"}, {"role": "user", "content": "Explain this"}], [], lambda *a, **k: {}, owner=True)

    def test_context_budget_is_local_and_bounded(self):
        messages = [
            {"role": "system", "content": "security policy"},
            {"role": "assistant", "content": "H" * 1800},
            {"role": "user", "content": "What is the root cause of this failure?"},
        ]
        with patch.dict(os.environ, {"LLM_CONTEXT_TOKENS": "1024", "LLM_OUTPUT_TOKENS": "256"}, clear=False):
            fitted = fit_messages(messages)
        self.assertEqual(fitted[-1]["content"], messages[-1]["content"])
        self.assertNotIn("H" * 1800, [item.get("content") for item in fitted])

    def test_oversized_user_message_is_rejected_without_truncation(self):
        user_text = "U" * 5000
        messages = [{"role": "system", "content": "security policy"}, {"role": "user", "content": user_text}]
        with patch.dict(os.environ, {"LLM_CONTEXT_TOKENS": "512", "LLM_OUTPUT_TOKENS": "128"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "context_budget_exceeded_user_message_too_large"):
                fit_messages(messages)
        self.assertEqual(messages[-1]["content"], user_text)

    def test_portfolio_and_telegram_can_share_same_planner_type(self):
        provider = FakeProvider()
        planner = ExecutivePlanner(provider)
        self.assertEqual(planner.router.provider.name, "openrouter")
        self.assertEqual(planner.router.choose_model("portfolio", [], intent="conversation"), "test/model")


if __name__ == "__main__":
    unittest.main()
