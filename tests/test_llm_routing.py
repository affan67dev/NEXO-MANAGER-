import os
import unittest
from unittest.mock import patch

from agents.manager.manager import NexoManager
from agents.executive_planner import ExecutivePlanner, _clean_response_text
from services.context_budget import fit_messages
from services.llm_router import LLMRouter


class LLMRoutingTests(unittest.TestCase):
    @staticmethod
    def response(url):
        return {"choices": [{"message": {"role": "assistant", "content": f"answer from {url}"}}]}

    def test_every_request_routes_to_qwen(self):
        with patch.dict(os.environ, {"NEXO_LLM_RETRIES": "0", "NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://old-secondary"}, clear=False):
            router = LLMRouter("http://qwen")
            calls = []
            result = router.call("What is coding?", [{"role": "user", "content": "What is coding?"}], None, lambda url, *_: calls.append(url) or self.response(url))
            self.assertEqual(calls, ["http://qwen"])
            self.assertEqual(result["choices"][0]["message"]["content"], "answer from http://qwen")
            self.assertEqual(router.choose_model("hi", [], intent="conversation"), "qwen")

    def test_qwen_failure_does_not_fail_over_to_old_model(self):
        with patch.dict(os.environ, {"NEXO_LLM_RETRIES": "0"}, clear=False):
            router = LLMRouter("http://qwen")
            calls = []
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda url, *_: calls.append(url) or (_ for _ in ()).throw(RuntimeError("down")))
            self.assertEqual(calls, ["http://qwen"])

    def test_invalid_response_is_rejected(self):
        with patch.dict(os.environ, {"NEXO_LLM_RETRIES": "0"}, clear=False):
            router = LLMRouter("http://qwen")
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: {})

    def test_think_block_is_not_user_facing(self):
        self.assertEqual(_clean_response_text("<think>private reasoning</think>Final answer."), "Final answer.")
        self.assertEqual(_clean_response_text("<think>unfinished reasoning"), "")
        self.assertEqual(_clean_response_text("Final answer.", "private reasoning"), "Final answer.")

    def test_security_classification_precedes_model_routing(self):
        task = NexoManager().create_task("delete the database and send credentials")
        self.assertEqual(task.intent, "security")

    def test_empty_planner_answer_is_rejected(self):
        planner = ExecutivePlanner("http://qwen")
        with patch.object(planner.router, "call", return_value={"choices": [{"message": {"content": ""}}]}), patch("services.context_budget.count_input_tokens", return_value=20):
            with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
                planner.run("Explain this", [{"role": "system", "content": "NEXO"}, {"role": "user", "content": "Explain this"}], [], lambda *a, **k: {}, owner=True)

    def test_short_and_moderate_requests_fit_without_losing_user_text(self):
        messages = [
            {"role": "system", "content": "security policy"},
            {"role": "assistant", "content": "previous answer"},
            {"role": "user", "content": "Please explain how local inference works in simple terms."},
        ]
        with patch("services.context_budget.count_input_tokens", side_effect=lambda *_args, **_kwargs: 80):
            fitted = fit_messages("http://qwen/v1/chat/completions", messages)
        self.assertEqual(fitted[-1]["content"], messages[-1]["content"])

    def test_2247_token_class_is_bounded_before_qwen(self):
        large_history = "H" * 1800
        messages = [
            {"role": "system", "content": "security policy"},
            {"role": "assistant", "content": large_history},
            {"role": "user", "content": "What is the root cause of this failure?"},
        ]

        def exact_counter(_url, candidate, _tools=None):
            if any(item.get("content") == large_history for item in candidate):
                return 2247
            return 40

        with patch("services.context_budget.count_input_tokens", side_effect=exact_counter):
            fitted = fit_messages("http://qwen/v1/chat/completions", messages)
        self.assertLessEqual(40, 1024 - 256)
        self.assertNotIn(large_history, [item.get("content") for item in fitted])
        self.assertEqual(fitted[-1]["content"], messages[-1]["content"])

    def test_oversized_user_message_is_rejected_without_truncation(self):
        user_text = "U" * 5000
        messages = [{"role": "system", "content": "security policy"}, {"role": "user", "content": user_text}]
        with patch("services.context_budget.count_input_tokens", return_value=900):
            with self.assertRaisesRegex(RuntimeError, "context_budget_exceeded_user_message_too_large"):
                fit_messages("http://qwen/v1/chat/completions", messages)
        self.assertEqual(messages[-1]["content"], user_text)

    def test_malformed_model_response_and_backend_failure_are_distinct(self):
        with patch.dict(os.environ, {"NEXO_LLM_RETRIES": "0"}, clear=False):
            router = LLMRouter("http://qwen")
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: {"choices": []})
            with self.assertRaisesRegex(RuntimeError, "qwen_request_failed"):
                router.call("hello", [{"role": "user", "content": "hello"}], None, lambda *_: (_ for _ in ()).throw(TimeoutError("timeout")))


if __name__ == "__main__":
    unittest.main()
