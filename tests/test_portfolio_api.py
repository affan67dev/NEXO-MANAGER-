from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import patch

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
if FASTAPI_AVAILABLE:
    import portfolio_api
    from fastapi.testclient import TestClient


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is not installed in the Android MVB test profile")
class PortfolioAPISecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "NEXO_PORTFOLIO_SESSION_SECRET": "test-only-portfolio-session-secret",
            "NEXO_PORTFOLIO_ALLOWED_ORIGINS": "https://portfolio.example",
            "NEXO_PORTFOLIO_COOKIE_SECURE": "true",
            "NEXO_PUBLIC_KNOWLEDGE_REFRESH_ON_STARTUP": "false",
            "NEXO_PORTFOLIO_RATE_LIMIT": "20",
            "NEXO_PORTFOLIO_RATE_WINDOW_SECONDS": "60",
        }
        self.patch = patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        portfolio_api.rate_limiter = portfolio_api.SlidingWindowRateLimiter()

    def tearDown(self):
        self.patch.stop()

    def test_session_cookie_is_signed_and_tamper_rejected(self):
        response = portfolio_api.Response()
        session_id = portfolio_api._session(response, None)
        cookie = next(value for key, value in response.raw_headers if key.decode() == "set-cookie")
        token = cookie.decode().split(";", 1)[0].split("=", 1)[1]
        self.assertEqual(portfolio_api._decode_session(token), session_id)
        parts = token.split(".")
        parts[0] = "tampered"
        self.assertIsNone(portfolio_api._decode_session(".".join(parts)))

    def test_public_origin_must_be_explicitly_allowlisted(self):
        self.assertTrue(portfolio_api._origin_allowed("https://portfolio.example"))
        self.assertFalse(portfolio_api._origin_allowed("https://evil.example"))
        self.assertTrue(portfolio_api._origin_allowed(None))

    def test_rate_limit_is_enforced_per_signed_session(self):
        limiter = portfolio_api.SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("visitor", limit=2, window_seconds=60, now=1))
        self.assertTrue(limiter.allow("visitor", limit=2, window_seconds=60, now=2))
        self.assertFalse(limiter.allow("visitor", limit=2, window_seconds=60, now=3))
        self.assertTrue(limiter.allow("other-visitor", limit=2, window_seconds=60, now=3))

    def test_api_requires_session_secret(self):
        with patch.dict(os.environ, {"NEXO_PORTFOLIO_SESSION_SECRET": ""}, clear=False):
            with self.assertRaises(Exception) as ctx:
                portfolio_api._session(portfolio_api.Response(), None)
            self.assertEqual(getattr(ctx.exception, "status_code", None), 503)

    def test_http_origin_and_session_boundary(self):
        with TestClient(portfolio_api.app) as client:
            with patch("portfolio_api.portfolio_ai.answer", return_value={
                "answer": "public answer", "action": "answer", "scope": "public_portfolio"
            }):
                denied = client.get("/api/portfolio/session", headers={"Origin": "https://evil.example"})
                self.assertEqual(denied.status_code, 403)

                created = client.get("/api/portfolio/session", headers={"Origin": "https://portfolio.example"})
                self.assertEqual(created.status_code, 200)
                self.assertIn("nexo_portfolio_session=", created.headers.get("set-cookie", ""))
                self.assertIn("HttpOnly", created.headers.get("set-cookie", ""))
                self.assertIn("Secure", created.headers.get("set-cookie", ""))
                self.assertIn("SameSite=none", created.headers.get("set-cookie", ""))

                response = client.post(
                    "/api/portfolio/chat",
                    headers={"Origin": "https://portfolio.example"},
                    json={"message": "What is OMNIX?"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["scope"], "public_portfolio")

    def test_malformed_session_cookie_is_replaced(self):
        with TestClient(portfolio_api.app) as client:
            response = client.post(
                "/api/portfolio/chat",
                headers={"Origin": "https://portfolio.example", "Cookie": "nexo_portfolio_session=forged"},
                json={"message": "What is OMNIX?"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("nexo_portfolio_session=", response.headers.get("set-cookie", ""))


if __name__ == "__main__":
    unittest.main()
