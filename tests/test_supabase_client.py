from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import httpx

from services.supabase_client import SupabaseClient


class SupabaseHealthCheckTests(unittest.TestCase):
    def make_client(self) -> SupabaseClient:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "public-test-key",
            },
            clear=False,
        ):
            return SupabaseClient()

    @patch("services.supabase_client.httpx.get")
    def test_public_key_accepted(self, get: Mock) -> None:
        get.return_value = Mock(status_code=200)
        result = self.make_client().health_check()
        self.assertEqual(result["status"], "credential_accepted")
        self.assertTrue(result["reachable"])
        self.assertTrue(result["credential_accepted"])
        get.assert_called_once_with(
            "https://example.supabase.co/auth/v1/settings",
            headers=self.make_client().headers,
            timeout=10.0,
        )

    @patch("services.supabase_client.httpx.get")
    def test_public_key_rejected(self, get: Mock) -> None:
        get.return_value = Mock(status_code=401)
        result = self.make_client().health_check()
        self.assertEqual(result["status"], "credential_rejected")
        self.assertTrue(result["reachable"])
        self.assertFalse(result["credential_accepted"])

    @patch("services.supabase_client.httpx.get")
    def test_endpoint_permission_failure_is_distinct(self, get: Mock) -> None:
        get.return_value = Mock(status_code=403)
        result = self.make_client().health_check()
        self.assertEqual(result["status"], "endpoint_permission_failure")
        self.assertTrue(result["reachable"])

    @patch("services.supabase_client.httpx.get")
    def test_network_failure_is_distinct(self, get: Mock) -> None:
        get.side_effect = httpx.ConnectError("offline")
        result = self.make_client().health_check()
        self.assertEqual(result["status"], "network_unreachable")
        self.assertFalse(result["reachable"])
        self.assertIsNone(result["http_status"])

    @patch("services.supabase_client.httpx.get")
    def test_server_failure_is_distinct(self, get: Mock) -> None:
        get.return_value = Mock(status_code=503)
        result = self.make_client().health_check()
        self.assertEqual(result["status"], "service_failure")
        self.assertTrue(result["reachable"])


if __name__ == "__main__":
    unittest.main()
