import os
import unittest
from unittest.mock import patch

from services.llm_router import LLMRouter


class LLMRoutingTests(unittest.TestCase):
    def test_default_keeps_primary_only(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEXO_QWEN_FALLBACK_ENABLED", None)
            os.environ.pop("NEXO_QWEN_URL", None)
            router = LLMRouter("http://llama")
            self.assertFalse(router.should_use_secondary("x" * 5000, []))
            calls = []
            result = router.call("simple", [{"role": "user", "content": "simple"}], None,
                                 lambda url, messages, tools: calls.append(url) or {"ok": True})
            self.assertEqual(result, {"ok": True})
            self.assertEqual(calls, ["http://llama"])

    def test_complex_request_prefers_qwen_when_explicitly_enabled(self):
        env = {"NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://qwen", "NEXO_QWEN_COMPLEXITY_CHARS": "100"}
        with patch.dict(os.environ, env, clear=False):
            router = LLMRouter("http://llama")
            calls = []
            router.call("x" * 120, [{"role": "user", "content": "x"}], None,
                        lambda url, messages, tools: calls.append(url) or {"model": url})
            self.assertEqual(calls[0], "http://qwen")

    def test_qwen_failure_falls_back_to_primary(self):
        env = {"NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://qwen", "NEXO_QWEN_COMPLEXITY_CHARS": "10"}
        with patch.dict(os.environ, env, clear=False):
            router = LLMRouter("http://llama")
            calls = []
            def fake_ask(url, messages, tools):
                calls.append(url)
                if url == "http://qwen":
                    raise RuntimeError("qwen_unavailable")
                return {"model": url}
            result = router.call("complex request", [{"role": "user", "content": "complex"}], None, fake_ask)
            self.assertEqual(result["model"], "http://llama")
            self.assertEqual(calls, ["http://qwen", "http://llama"])

    def test_same_endpoint_never_counts_as_secondary(self):
        env = {"NEXO_QWEN_FALLBACK_ENABLED": "true", "NEXO_QWEN_URL": "http://llama"}
        with patch.dict(os.environ, env, clear=False):
            router = LLMRouter("http://llama")
            self.assertFalse(router.should_use_secondary("x" * 5000, []))


if __name__ == "__main__":
    unittest.main()
