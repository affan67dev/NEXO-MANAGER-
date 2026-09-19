import unittest
from integrations.email.adapter import EmailAdapter, EmailMessage
from integrations.whatsapp.adapter import WhatsAppAdapter
from core.channel_gateway import ChannelGateway, ChannelMessage


class EmailAdapterTests(unittest.TestCase):
    def test_unconfigured_provider_is_explicit(self):
        result = EmailAdapter().send(EmailMessage(sender="", recipients=("a@example.com",), text="x"))
        self.assertFalse(result["ok"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "PROVIDER_CONFIGURATION_REQUIRED")

    def test_mock_provider_boundary(self):
        class Provider:
            def send(self, message):
                return {"ok": True, "message_id": "m1"}
            def receive(self, limit=20):
                return []
            def search(self, query, limit=20):
                return []
        result = EmailAdapter(Provider()).send(
            EmailMessage(sender="a@example.com", recipients=("b@example.com",), text="hello")
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["message_id"], "m1")


class WhatsAppAdapterTests(unittest.TestCase):
    def test_webhook_normalization(self):
        messages = WhatsAppAdapter().receive_message({
            "messages": [
                {"from": "123", "id": "m1", "text": {"body": "hello"}},
                {"from": "", "text": {"body": "ignored"}},
            ]
        })
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].text, "hello")

    def test_unconfigured_send_never_reports_success(self):
        result = WhatsAppAdapter().send_message("123", "hello")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "PROVIDER_CONFIGURATION_REQUIRED")


class ChannelGatewayTests(unittest.TestCase):
    def test_all_channels_use_one_handler(self):
        calls = []
        gateway = ChannelGateway(lambda message: calls.append(message.channel) or "ALEX reply")
        for channel in ("telegram", "whatsapp", "email"):
            reply = gateway.handle(ChannelMessage(channel=channel, sender="user", text="hello"))
            self.assertEqual(reply.text, "ALEX reply")
        self.assertEqual(calls, ["telegram", "whatsapp", "email"])


if __name__ == "__main__":
    unittest.main()
