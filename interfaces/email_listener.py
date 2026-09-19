from __future__ import annotations

from typing import Protocol
from integrations.email.adapter import EmailMessage


class EmailListener(Protocol):
    """Provider-neutral inbound email listener boundary."""

    def receive(self, *, limit: int = 20) -> list[EmailMessage]:
        ...
