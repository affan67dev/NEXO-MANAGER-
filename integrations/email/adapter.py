from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content_type: str = "application/octet-stream"
    content: bytes = b""


@dataclass(frozen=True)
class EmailMessage:
    sender: str
    recipients: tuple[str, ...]
    subject: str = ""
    text: str = ""
    message_id: str | None = None
    attachments: tuple[EmailAttachment, ...] = field(default_factory=tuple)


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> Mapping[str, Any]: ...
    def receive(self, *, limit: int = 20) -> Sequence[EmailMessage]: ...
    def search(self, query: str, *, limit: int = 20) -> Sequence[EmailMessage]: ...


class EmailAdapter:
    """Provider-neutral email boundary.

    A provider must be injected by the runtime. No credentials or network
    client are created by this adapter itself. Without a provider, operations
    return an explicit provider-configuration result rather than pretending
    that mail was sent or received.
    """

    channel = "email"

    def __init__(self, provider: EmailProvider | None = None) -> None:
        self.provider = provider

    @property
    def configured(self) -> bool:
        return self.provider is not None

    def _required(self) -> dict[str, Any]:
        return {
            "ok": False,
            "verified": False,
            "status": "PROVIDER_CONFIGURATION_REQUIRED",
            "error": "email_provider_not_configured",
        }

    def send(self, message: EmailMessage) -> dict[str, Any]:
        if not self.provider:
            return self._required()
        result = dict(self.provider.send(message))
        result.setdefault("channel", self.channel)
        result.setdefault("verified", bool(result.get("ok")))
        return result

    def receive(self, *, limit: int = 20) -> dict[str, Any]:
        if not self.provider:
            return self._required()
        messages = list(self.provider.receive(limit=max(1, min(limit, 100))))
        return {"ok": True, "verified": True, "status": "RECEIVED", "messages": messages}

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        if not self.provider:
            return self._required()
        messages = list(self.provider.search(query.strip(), limit=max(1, min(limit, 100))))
        return {"ok": True, "verified": True, "status": "SEARCHED", "messages": messages}

    def reply(self, original: EmailMessage, text: str) -> dict[str, Any]:
        if not original.sender:
            return {"ok": False, "verified": False, "error": "missing_original_sender"}
        reply = EmailMessage(
            sender="",
            recipients=(original.sender,),
            subject=original.subject if original.subject.lower().startswith("re:") else f"Re: {original.subject}",
            text=text,
            attachments=(),
        )
        return self.send(reply)
