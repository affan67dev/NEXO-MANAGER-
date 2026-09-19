from __future__ import annotations

from integrations.email.adapter import EmailAdapter, EmailMessage


class EmailService:
    """Thin service facade; ALEX business logic stays outside the channel adapter."""

    def __init__(self, adapter: EmailAdapter | None = None) -> None:
        self.adapter = adapter or EmailAdapter()

    def send(self, message: EmailMessage) -> dict:
        return self.adapter.send(message)

    def receive(self, *, limit: int = 20) -> dict:
        return self.adapter.receive(limit=limit)

    def search(self, query: str, *, limit: int = 20) -> dict:
        return self.adapter.search(query, limit=limit)

    def reply(self, original: EmailMessage, text: str) -> dict:
        return self.adapter.reply(original, text)
