from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.identity import resolve_telegram_identity
from core.request_context import RequestContext


class TelegramIdentityTests(unittest.TestCase):
    def test_configured_numeric_id_is_admin(self):
        with patch.dict(os.environ, {"NEXO_OWNER_TELEGRAM_USER_ID": "123456"}, clear=False):
            identity = resolve_telegram_identity(123456)
        self.assertEqual(identity.telegram_user_id, "123456")
        self.assertEqual(identity.role, "admin")
        self.assertTrue(identity.is_admin)

    def test_other_numeric_id_is_public_client(self):
        with patch.dict(os.environ, {"NEXO_OWNER_TELEGRAM_USER_ID": "123456"}, clear=False):
            identity = resolve_telegram_identity(987654)
        self.assertEqual(identity.role, "public_client")
        self.assertFalse(identity.is_admin)

    def test_username_or_message_cannot_change_role(self):
        with patch.dict(os.environ, {"NEXO_OWNER_TELEGRAM_USER_ID": "123456"}, clear=False):
            identity = resolve_telegram_identity("987654")
        self.assertEqual(identity.role, "public_client")

    def test_invalid_telegram_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_telegram_user_id"):
            resolve_telegram_identity("not-a-telegram-id")

    def test_request_context_uses_explicit_server_derived_role(self):
        admin = RequestContext.telegram(123456, "admin")
        client = RequestContext.telegram(987654, "public_client")
        self.assertEqual((admin.actor_type, admin.scope), ("admin", "owner_admin"))
        self.assertEqual((client.actor_type, client.scope), ("public_client", "telegram_public"))

    def test_invalid_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_telegram_role"):
            RequestContext.telegram(123456, "owner")


if __name__ == "__main__":
    unittest.main()
