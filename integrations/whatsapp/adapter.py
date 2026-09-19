from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class WhatsAppMessage:
    sender: str
    text: str
    message_id: str | None = None


class WhatsAppProvider(Protocol):
    def find_contact(self, query: str) -> Mapping[str, Any]: ...
    def get_conversation(self, contact: str, *, limit: int = 20) -> list[WhatsAppMessage]: ...
    def send_message(self, recipient: str, text: str) -> Mapping[str, Any]: ...
    def send_media(self, recipient: str, media: bytes, *, filename: str = "media") -> Mapping[str, Any]: ...


class WhatsAppAdapter:
    """Safe boundary for an authorized WhatsApp Business/API provider.

    No browser automation, WhatsApp Web scraping, or fabricated send success is
    performed. Provider methods are invoked only when an authorized provider
    has been injected.
    """

    channel = "whatsapp"

    def __init__(self, provider: WhatsAppProvider | None = None) -> None:
        self.provider = provider

    @property
    def configured(self) -> bool:
        return self.provider is not None

    def _required(self) -> dict[str, Any]:
        return {
            "ok": False,
            "verified": False,
            "status": "PROVIDER_CONFIGURATION_REQUIRED",
            "error": "whatsapp_provider_not_configured",
        }

    def find_contact(self, query: str) -> dict[str, Any]:
        if not self.provider:
            return self._required()
        return dict(self.provider.find_contact(query.strip()))

    def get_conversation(self, contact: str, *, limit: int = 20) -> dict[str, Any]:
        if not self.provider:
            return self._required()
        messages = self.provider.get_conversation(contact, limit=max(1, min(limit, 100)))
        return {"ok": True, "verified": True, "status": "RECEIVED", "messages": list(messages)}

    def send_message(self, recipient: str, text: str) -> dict[str, Any]:
        if not self.provider:
            return self._required()
        result = dict(self.provider.send_message(recipient, text))
        result.setdefault("channel", self.channel)
        result.setdefault("verified", bool(result.get("ok")))
        return result

    def send_media(self, recipient: str, media: bytes, *, filename: str = "media") -> dict[str, Any]:
        if not self.provider:
            return self._required()
        result = dict(self.provider.send_media(recipient, media, filename=filename))
        result.setdefault("channel", self.channel)
        result.setdefault("verified", bool(result.get("ok")))
        return result

    def receive_message(self, payload: dict[str, Any]) -> list[WhatsAppMessage]:
        return self.parse_webhook(payload)

    def parse_webhook(self, payload: dict[str, Any]) -> list[WhatsAppMessage]:
        messages: list[WhatsAppMessage] = []
        for item in payload.get("messages", []):
            if not isinstance(item, dict):
                continue
            sender = str(item.get("from", "")).strip()
            text = item.get("text", "")
            if isinstance(text, dict):
                text = text.get("body", "")
            text = str(text or "").strip()
            if sender and text:
                messages.append(
                    WhatsAppMessage(sender=sender, text=text, message_id=item.get("id"))
                )
        return messages

    def prepare_reply(self, message: WhatsAppMessage, reply: str) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "recipient": message.sender,
            "text": reply,
            "requires_authorized_api": True,
            "status": "READY_FOR_SEND",
        }
