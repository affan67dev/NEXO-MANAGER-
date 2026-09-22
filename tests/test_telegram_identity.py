from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.identity import authorize_bot_update, resolve_bot_identity, resolve_telegram_identity
from core.request_context import RequestContext


class TelegramIdentityTests(unittest.TestCase):
    def test_configured_numeric_id_is_admin(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "123456", "NEXO_OWNER_TELEGRAM_USER_ID": ""}, clear=False):
            identity = resolve_telegram_identity(123456)
        self.assertEqual(identity.role, "admin")

    def test_other_numeric_id_is_public_client(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "123456"}, clear=False):
            self.assertEqual(resolve_telegram_identity(987654).role, "public_client")

    def test_public_bot_never_inherits_admin_role(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "123456"}, clear=False):
            identity = resolve_bot_identity("public", 123456)
        self.assertEqual(identity.role, "public_client")
        self.assertTrue(authorize_bot_update("public", 123456))

    def test_admin_bot_allows_only_configured_id(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "123456"}, clear=False):
            self.assertTrue(authorize_bot_update("admin", 123456))
            self.assertFalse(authorize_bot_update("admin", 987654))

    def test_invalid_telegram_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_telegram_user_id"):
            resolve_telegram_identity("not-a-telegram-id")

    def test_request_context_derives_role_from_bot_identity(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_USER_ID": "123456"}, clear=False):
            admin = RequestContext.telegram(123456, "admin")
            public = RequestContext.telegram(123456, "public")
        self.assertEqual((admin.actor_type, admin.scope), ("admin", "owner_admin"))
        self.assertEqual((public.actor_type, public.scope), ("public_client", "telegram_public"))

    def test_invalid_bot_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_bot_role"):
            RequestContext.telegram(123456, "owner")


if __name__ == "__main__":
    unittest.main()
