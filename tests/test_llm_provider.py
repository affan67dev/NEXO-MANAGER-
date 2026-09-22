from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import unittest
from unittest.mock import patch
from email.utils import format_datetime

import httpx

from services.llm_provider import LLMConfig, OpenRouterProvider


class LLMProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "LLM_PROVIDER": "openrouter",
            "LLM_API_KEY": "test-secret-key",
            "LLM_MODEL": "test/model",
            "LLM_FALLBACK_MODELS": "",
            "LLM_BASE_URL": "https://openrouter.ai/api/v1",
            "LLM_TIMEOUT_SECONDS": "1",
            "LLM_RETRIES": "1",
            "LLM_BACKOFF_SECONDS": "0.5",
            "LLM_CONTEXT_TOKENS": "4096",
            "LLM_OUTPUT_TOKENS": "512",
        }

    def provider(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return OpenRouterProvider(LLMConfig.from_env(), client=client)

    @staticmethod
    def success_response():
        return {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}

    def test_configuration_requires_provider_key_model_and_base_url(self):
        with patch.dict(os.environ, self.env, clear=False):
            config = LLMConfig.from_env()
            self.assertEqual(config.provider, "openrouter")
            self.assertEqual(config.model, "test/model")
            self.assertEqual(config.fallback_models, ())
        for key in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
            env = dict(self.env)
            env.pop(key)
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError):
                    LLMConfig.from_env()

    def test_base_url_must_be_verified_openrouter_https_endpoint(self):
        for base_url in ("http://127.0.0.1:8080/v1", "https://example.invalid/api/v1", "https://openrouter.ai/other"):
            with patch.dict(os.environ, dict(self.env, LLM_BASE_URL=base_url), clear=True):
                with self.assertRaisesRegex(RuntimeError, "llm_base_url_invalid"):
                    LLMConfig.from_env()
        with patch.dict(os.environ, dict(self.env, LLM_BASE_URL="https://eu.openrouter.ai/api/v1"), clear=True):
            self.assertEqual(LLMConfig.from_env().base_url, "https://eu.openrouter.ai/api/v1")

    def test_fallback_models_are_optional_and_exclude_primary_duplicates(self):
        env = dict(self.env, LLM_FALLBACK_MODELS="backup/a, backup/b, test/model, backup/a")
        with patch.dict(os.environ, env, clear=True):
            config = LLMConfig.from_env()
        self.assertEqual(config.fallback_models, ("backup/a", "backup/b"))

    def test_success_and_server_side_auth_header(self):
        seen = {}
        def handler(request):
            seen["authorization"] = request.headers.get("authorization")
            seen["payload"] = request.read().decode()
            return httpx.Response(200, json=self.success_response())
        with patch.dict(os.environ, self.env, clear=True):
            result = self.provider(handler).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        self.assertEqual(seen["authorization"], "Bearer test-secret-key")
        self.assertNotIn('"models"', seen["payload"])

    def test_fallback_models_are_sent_only_when_configured(self):
        seen = []
        def handler(request):
            import json
            seen.append(json.loads(request.read().decode()))
            return httpx.Response(200, json=self.success_response())
        env = dict(self.env, LLM_FALLBACK_MODELS="backup/a,backup/b")
        with patch.dict(os.environ, env, clear=True):
            self.provider(handler).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(seen[0]["model"], "test/model")
        self.assertEqual(seen[0]["models"], ["backup/a", "backup/b"])

    def test_429_numeric_retry_after_is_used(self):
        calls = []
        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
            return httpx.Response(200, json=self.success_response())
        env = dict(self.env, LLM_RETRIES="1", LLM_BACKOFF_SECONDS="0.5")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep") as sleep:
            result = self.provider(handler).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        sleep.assert_called_once_with(7.0)

    def test_429_http_date_retry_after_is_used(self):
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=8)
        calls = []
        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": format_datetime(retry_at, usegmt=True)})
            return httpx.Response(200, json=self.success_response())
        env = dict(self.env, LLM_RETRIES="1", LLM_BACKOFF_SECONDS="0.5")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep") as sleep:
            self.provider(handler).complete([{"role": "user", "content": "hello"}])
        delay = sleep.call_args.args[0]
        self.assertGreaterEqual(delay, 0)
        self.assertLessEqual(delay, 30.0)
        self.assertGreater(delay, 0)

    def test_429_malformed_retry_after_uses_exponential_backoff(self):
        calls = []
        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "not-a-delay"})
            return httpx.Response(200, json=self.success_response())
        env = dict(self.env, LLM_RETRIES="1", LLM_BACKOFF_SECONDS="0.5")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep") as sleep:
            self.provider(handler).complete([{"role": "user", "content": "hello"}])
        sleep.assert_called_once_with(0.5)

    def test_429_missing_retry_after_uses_exponential_backoff(self):
        calls = []
        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429)
            return httpx.Response(200, json=self.success_response())
        env = dict(self.env, LLM_RETRIES="1", LLM_BACKOFF_SECONDS="0.5")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep") as sleep:
            self.provider(handler).complete([{"role": "user", "content": "hello"}])
        sleep.assert_called_once_with(0.5)

    def test_429_retry_after_is_bounded(self):
        def handler(request):
            return httpx.Response(429, headers={"Retry-After": "999999999"})
        env = dict(self.env, LLM_RETRIES="1")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "llm_provider_unavailable"):
                self.provider(handler).complete([{"role": "user", "content": "hello"}])
        sleep.assert_called_once_with(30.0)

    def test_repeated_429_ends_after_configured_retry_limit(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "0"})
        env = dict(self.env, LLM_RETRIES="2")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "llm_provider_unavailable"):
                self.provider(handler).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(len(calls), 3)

    def test_rate_limit_and_server_error_are_bounded(self):
        for status in (429, 503):
            calls = []
            def handler(request, status=status):
                calls.append(1)
                return httpx.Response(status)
            env = dict(self.env, LLM_RETRIES="1", LLM_BACKOFF_SECONDS="0")
            with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "llm_provider_unavailable"):
                    self.provider(handler).complete([{"role": "user", "content": "hello"}])
            self.assertEqual(len(calls), 2)

    def test_transient_503_is_successful_after_bounded_retry(self):
        calls = []
        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=self.success_response())
        env = dict(self.env, LLM_RETRIES="1", LLM_BACKOFF_SECONDS="0")
        with patch.dict(os.environ, env, clear=True), patch("services.llm_provider.time.sleep"):
            result = self.provider(handler).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        self.assertEqual(len(calls), 2)

    def test_timeout_is_controlled(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out", request=request)
        env = dict(self.env, LLM_RETRIES="0")
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "llm_provider_timeout"):
                self.provider(handler).complete([{"role": "user", "content": "hello"}])

    def test_network_failure_is_controlled(self):
        def handler(request):
            raise httpx.ConnectError("offline", request=request)
        env = dict(self.env, LLM_RETRIES="0")
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "llm_provider_network_failure"):
                self.provider(handler).complete([{"role": "user", "content": "hello"}])

    def test_unavailable_model_and_auth_failures_are_controlled(self):
        for status, error in ((404, "llm_model_unavailable"), (401, "llm_provider_authorization_failed"), (403, "llm_provider_authorization_failed")):
            def handler(request, status=status):
                return httpx.Response(status)
            with patch.dict(os.environ, dict(self.env, LLM_RETRIES="0"), clear=True):
                with self.assertRaisesRegex(RuntimeError, error):
                    self.provider(handler).complete([{"role": "user", "content": "hello"}])

    def test_malformed_and_empty_responses_are_rejected(self):
        handlers = [
            lambda request: httpx.Response(200, text="not-json"),
            lambda request: httpx.Response(200, json={"choices": []}),
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
        ]
        with patch.dict(os.environ, dict(self.env, LLM_RETRIES="0"), clear=True):
            for handler in handlers:
                with self.assertRaisesRegex(RuntimeError, "llm_provider_malformed_response"):
                    self.provider(handler).complete([{"role": "user", "content": "hello"}])

    def test_secret_never_enters_provider_error_or_log_message(self):
        secret = self.env["LLM_API_KEY"]
        records = []
        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler_log = Capture()
        logger = logging.getLogger("nexo.llm_provider")
        logger.addHandler(handler_log)
        try:
            def handler(request):
                return httpx.Response(500)
            with patch.dict(os.environ, dict(self.env, LLM_RETRIES="0"), clear=True):
                with self.assertRaises(RuntimeError) as caught:
                    self.provider(handler).complete([{"role": "user", "content": "hello"}])
            self.assertNotIn(secret, str(caught.exception))
            self.assertNotIn(secret, "\n".join(records))
        finally:
            logger.removeHandler(handler_log)


if __name__ == "__main__":
    unittest.main()
