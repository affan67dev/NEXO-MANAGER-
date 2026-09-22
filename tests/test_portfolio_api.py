from __future__ import annotations

import unittest

import portfolio_api


class PortfolioApiBoundaryTests(unittest.TestCase):
    def test_session_cookie_is_signed_and_tampering_is_rejected(self):
        session_id = "a" * 43
        signed = portfolio_api._sign_session(session_id)
        self.assertEqual(portfolio_api._verify_session(signed), session_id)
        tampered = signed[:-1] + ("0" if signed[-1] != "0" else "1")
        self.assertIsNone(portfolio_api._verify_session(tampered))

    def test_unsigned_or_malformed_cookie_is_rejected(self):
        self.assertIsNone(portfolio_api._verify_session("a" * 43))
        self.assertIsNone(portfolio_api._verify_session("known-session." + "x" * 10))

    def test_origin_allowlist_never_accepts_empty_configuration(self):
        original = portfolio_api.MAX_ORIGINS
        try:
            portfolio_api.MAX_ORIGINS = ()
            self.assertFalse(portfolio_api._origin_allowed("https://portfolio.example"))
        finally:
            portfolio_api.MAX_ORIGINS = original

    def test_configured_origin_is_exact_match(self):
        original = portfolio_api.MAX_ORIGINS
        try:
            portfolio_api.MAX_ORIGINS = ("https://portfolio.example",)
            self.assertTrue(portfolio_api._origin_allowed("https://portfolio.example"))
            self.assertFalse(portfolio_api._origin_allowed("https://evil.example"))
            self.assertFalse(portfolio_api._origin_allowed(None))
        finally:
            portfolio_api.MAX_ORIGINS = original


if __name__ == "__main__":
    unittest.main()
