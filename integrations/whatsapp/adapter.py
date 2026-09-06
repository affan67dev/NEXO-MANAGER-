from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class WhatsAppMessage:
    sender: str
    text: str
    message_id: str | None = None

class WhatsAppAdapter:
    """Safe interface for an authorized WhatsApp Business/API connector."""

    def parse_webhook(self, payload: dict[str, Any]) -> list[WhatsAppMessage]:
        messages: list[WhatsAppMessage] = []
        for item in payload.get("messages", []):
            text = item.get("text", "")
            sender = item.get("from", "")
            if sender and text:
                messages.append(
                    WhatsAppMessage(
                        sender=sender,
                        text=text,
                        message_id=item.get("id")
                    )
                )
        return messages

    def prepare_reply(self, message: WhatsAppMessage, reply: str) -> dict[str, Any]:
        return {
            "channel": "whatsapp",
            "recipient": message.sender,
            "text": reply,
            "requires_authorized_api": True,
            "status": "READY_FOR_SEND"
        }
