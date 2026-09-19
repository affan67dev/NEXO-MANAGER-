from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.identity import authorize_bot_update, resolve_telegram_identity
from core.request_context import RequestContext


class TelegramIdentityTests(unittest.TestCase):
    def test_configured_numeric_id_is_admin(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            identity = resolve_telegram_identity(8921221615)
        self.assertEqual(identity.telegram_user_id, "8921221615")
        self.assertEqual(identity.role, "admin")
        self.assertTrue(identity.is_admin)

    def test_other_numeric_id_is_public_client(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            identity = resolve_telegram_identity(987654)
        self.assertEqual(identity.role, "public_client")
        self.assertFalse(identity.is_admin)

    def test_admin_bot_allows_only_configured_numeric_id(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            self.assertTrue(authorize_bot_update("admin", 8921221615))
            self.assertFalse(authorize_bot_update("admin", 987654))

    def test_public_bot_allows_public_identity(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            self.assertTrue(authorize_bot_update("public", 987654))
            self.assertFalse(authorize_bot_update("public", 8921221615))

    def test_username_or_message_cannot_change_role(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            identity = resolve_telegram_identity("987654")
        self.assertEqual(identity.role, "public_client")

    def test_invalid_telegram_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_telegram_user_id"):
            resolve_telegram_identity("not-a-telegram-id")

    def test_request_context_is_derived_from_server_identity(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "8921221615"}, clear=False):
            admin = RequestContext.telegram(8921221615)
            client = RequestContext.telegram(987654)
        self.assertEqual((admin.actor_type, admin.scope), ("admin", "owner_admin"))
        self.assertEqual((client.actor_type, client.scope), ("public_client", "telegram_public"))

    def test_invalid_bot_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_bot_role"):
            authorize_bot_update("unknown", 8921221615)


if __name__ == "__main__":
    unittest.main()
