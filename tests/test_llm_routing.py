import os
import unittest
from unittest.mock import patch

from agents.manager.manager import NexoManager
from agents.executive_planner import ExecutivePlanner, _clean_response_text
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

    def test_security_classification_precedes_model_routing(self):
        task = NexoManager().create_task("delete the database and send credentials")
        self.assertEqual(task.intent, "security")

    def test_empty_planner_answer_is_rejected(self):
        planner = ExecutivePlanner("http://qwen")
        with patch.object(planner.router, "call", return_value={"choices": [{"message": {"content": ""}}]}):
            with self.assertRaisesRegex(RuntimeError, "empty_model_response"):
                planner.run("Explain this", [{"role": "user", "content": "Explain this"}], [], lambda *a, **k: {}, owner=True)


if __name__ == "__main__":
    unittest.main()
